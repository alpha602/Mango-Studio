import os
import re
import json
import string
import logging
import time
import winreg
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QThread, Signal

from core.config import AppConfig
from data.models import Game, LauncherType, LauncherInfo, ScanResult
from data.database import Database

# Erweiterte Blacklist für Custom Folders (Punkt 3)
BLACKLIST_SUBSTRINGS = (
    "epic online services", "steamworks", "source sdk", "sdk base", "redistributable", "directx", "vcredist", "vc_redist",
    "dedicated server", "unreal engine", "unity hub", "wallpaper engine", "game launcher", "steam client", "proton",
    "minecraft launcher", "epic games launcher", "riot client", "ubisoft connect", "gog galaxy", "wargaming game center", "xna framework",
    "vpn", "qwen", "process", "cefprocess", "chrome", "firefox", "edge", "browser", "setup", "install", "uninstall",
    "update", "patch", "unins", "crash", "helper", "service"
)

BLACKLIST_REGEX = (
    r"^battle\.net[\s._-]*\d+$", r"^agent$", r"^blizzard$", r"^launcher$", r"^client$", r"^eos$", r"^redist$",
    r"^prerequisites$", r"^dotnet$", r"^games$", r"^shareplay$", r"^steam$", r"^common$",
)
_BLACKLIST_COMPILED = tuple(re.compile(p) for p in BLACKLIST_REGEX)

class ScanThread(QThread):
    scan_finished = Signal(object)
    scan_error = Signal(str)
    def __init__(self, scanner: "Scanner", parent=None):
        super().__init__(parent)
        self._scanner = scanner
    def run(self):
        try: self.scan_finished.emit(self._scanner.full_scan())
        except Exception as e:
            logging.error(f"Scan-Thread fehlgeschlagen: {e}", exc_info=True)
            self.scan_error.emit(str(e))

class Scanner:
    LAUNCHER_PATHS = {
        LauncherType.STEAM: ["Program Files (x86)/Steam", "Program Files/Steam", "Steam"],
        LauncherType.EPIC_GAMES: ["Program Files/Epic Games", "Program Files (x86)/Epic Games", "Epic Games"],
        LauncherType.GOG_GALAXY: ["Program Files (x86)/GOG Galaxy/Games", "Program Files/GOG Galaxy/Games", "GOG Games", "Program Files (x86)/GOG Galaxy"],
        LauncherType.BATTLE_NET: ["Program Files (x86)/Blizzard Entertainment", "Program Files/Blizzard Entertainment", "Program Files (x86)/Battle.net"],
        LauncherType.EA_APP: ["Program Files/EA Games", "Program Files (x86)/EA Games", "Program Files (x86)/Origin Games", "Program Files/Origin Games"],
        LauncherType.UBISOFT: ["Program Files (x86)/Ubisoft/Ubisoft Game Launcher/games", "Program Files/Ubisoft/Ubisoft Game Launcher/games", "Program Files (x86)/Ubisoft/Ubisoft Game Launcher"],
        LauncherType.XBOX: ["XboxGames"],
        LauncherType.RIOT: ["Riot Games", "Program Files/Riot Games"],
        LauncherType.GAIJIN: ["Program Files (x86)/Gaijin", "Program Files/Gaijin"],
        LauncherType.AMAZON: ["Amazon Games", "Program Files/Amazon Games"],
        LauncherType.ITCH_IO: [],
        LauncherType.STANDALONE: [],
    }
    EPIC_SKIP_DIRS = {"launcher", "epic online services", "directxredist", "prerequisites", "eos", "epicgameslauncher"}
    SKIP_EXE_WORDS = ("uninstall", "unins", "setup", "redist", "vcredist", "directx", "crash", "anticheat", "easyanticheat", "beservice", "update", "patch", "installer", "config", "settings", "setupgame", "vpn", "qwen", "cef")
    SKIP_DIR_NAMES = {"redist", "_commonredist", "commonredist", "directx", "vcredist", "prerequisites", "support", "dotnet", "webview", "mono", "sdk", "tools", "editor", "crashhandler", "anticheat", "vpn", "qwen"}
    
    # Mindestgröße für Custom Folder .exe Dateien (20 MB), um Tools/VPNs auszusortieren
    MIN_CUSTOM_EXE_SIZE = 20 * 1024 * 1024 

    def __init__(self, config: AppConfig, database: Database):
        self.config = config
        self.db = database

    def should_perform_scan(self) -> bool:
        return self.db.get_game_count() == 0

    def full_scan(self) -> ScanResult:
        start_time = time.time()
        result = ScanResult()
        logging.warning("═══ Vollständiger Spiele-Scan gestartet ═══")
        drives = self._detect_available_drives()

        for launcher_type in LauncherType:
            if launcher_type == LauncherType.UNKNOWN: continue
            try: result.games_found.extend(self._scan_launcher(launcher_type, drives))
            except Exception as e:
                logging.error(f"Fehler beim Scannen von {launcher_type.name}: {e}")
                result.errors.append(str(e))

        result.games_found = [g for g in result.games_found if not self._is_blacklisted(g.name)]
        
        seen = set()
        unique_games = []
        for game in result.games_found:
            key = (game.name.lower(), game.launcher_type, str(game.executable_path).lower())
            if key not in seen:
                seen.add(key)
                unique_games.append(game)
        result.games_found = unique_games

        state_map = self.db.get_game_state_map()
        for game in result.games_found:
            key = (game.name.lower(), game.launcher_type.name, str(game.executable_path).lower())
            hidden, favorite = state_map.get(key, (False, False))
            game.is_hidden, game.is_favorite = hidden, favorite

        if result.games_found:
            self.db.clear_all_games()
            self.db.add_games_bulk(result.games_found)

        self._save_detected_launchers(result, drives)
        result.scan_duration_seconds = time.time() - start_time
        logging.warning(f"═══ Scan abgeschlossen in {result.scan_duration_seconds:.2f}s – {result.total_games} Spiele ═══")
        return result

    @staticmethod
    def _is_blacklisted(name: str) -> bool:
        lower = name.lower().strip()
        if any(token in lower for token in BLACKLIST_SUBSTRINGS): return True
        return any(pattern.match(lower) for pattern in _BLACKLIST_COMPILED)

    def _detect_available_drives(self) -> List[str]:
        return [f"{l}:\\" for l in string.ascii_uppercase if os.path.exists(f"{l}:\\")]

    def _scan_launcher(self, launcher_type: LauncherType, drives: List[str]) -> List[Game]:
        mapper = {
            LauncherType.STEAM: self._scan_steam, LauncherType.EPIC_GAMES: self._scan_epic,
            LauncherType.GOG_GALAXY: self._scan_gog, LauncherType.STANDALONE: self._scan_custom_folders,
            LauncherType.BATTLE_NET: self._scan_folder_based, LauncherType.EA_APP: self._scan_folder_based,
            LauncherType.UBISOFT: self._scan_folder_based, LauncherType.XBOX: self._scan_folder_based,
            LauncherType.RIOT: self._scan_folder_based, LauncherType.GAIJIN: self._scan_folder_based,
            LauncherType.AMAZON: self._scan_folder_based, LauncherType.ITCH_IO: self._scan_itch,
        }
        func = mapper.get(launcher_type)
        return func(launcher_type, drives) if func else []

    @staticmethod
    def _get_folder_size(folder: Path) -> int:
        total = 0
        try:
            for dp, dn, fn in os.walk(folder):
                for f in fn:
                    fp = os.path.join(dp, f)
                    try:
                        if os.path.isfile(fp) and not os.path.islink(fp): total += os.path.getsize(fp)
                    except OSError: pass
        except OSError: pass
        return total

    def _create_game_with_size(self, name: str, exe: Path, l_type: LauncherType, install: Path, **kwargs) -> Game:
        size = self._get_folder_size(install) if install.exists() else 0
        return Game(name=name, executable_path=exe, launcher_type=l_type, install_path=install, size_bytes=size, **kwargs)

    def _scan_custom_folders(self, launcher_type: LauncherType, drives: List[str]) -> List[Game]:
        games, seen_exes = [], set()
        for root_raw in self.config.custom_scan_folders:
            root = Path(root_raw)
            if not root.exists(): continue
            groups = {}
            try:
                for exe_file in root.rglob("*.exe"):
                    rel = exe_file.relative_to(root)
                    if len(rel.parts) - 1 > 3 or self._is_skip_exe(exe_file.name): continue
                    if any(p.lower() in self.SKIP_DIR_NAMES for p in rel.parts[:-1]): continue
                    
                    # Punkt 3: Dateigrößen-Check für Custom Folders
                    try:
                        if exe_file.stat().st_size < self.MIN_CUSTOM_EXE_SIZE: continue
                    except OSError: continue
                    
                    groups.setdefault(exe_file.parent, []).append(exe_file)
            except (PermissionError, OSError): continue

            for directory, exes in groups.items():
                chosen = exes if directory == root else [self._pick_main_exe(directory, exes)]
                for exe_file in chosen:
                    ek = str(exe_file).lower()
                    if ek in seen_exes: continue
                    seen_exes.add(ek)
                    games.append(self._create_game_with_size(exe_file.stem, exe_file, LauncherType.STANDALONE, exe_file.parent))
        return games

    @staticmethod
    def _pick_main_exe(directory: Path, exes: List[Path]) -> Path:
        fn = directory.name.lower()
        for e in exes:
            if e.stem.lower() == fn: return e
        for e in exes:
            if fn in e.stem.lower(): return e
        return max(exes, key=lambda f: f.stat().st_size)

    def _scan_steam(self, launcher_type: LauncherType, drives: List[str]) -> List[Game]:
        games, seen = [], set()
        for sr in self._find_steam_roots(drives):
            sa = sr / "steamapps"
            if not sa.exists(): continue
            for acf in sa.glob("appmanifest_*.acf"):
                meta = self._parse_acf(acf)
                appid, name, inst = meta.get("appid", ""), meta.get("name", "").strip(), meta.get("installdir", "").strip()
                if not name or not inst or not (int(meta.get("StateFlags", "0")) & 4): continue
                folder = sa / "common" / inst
                fk = str(folder).lower()
                if not folder.exists() or fk in seen: continue
                seen.add(fk)
                exe = self._find_executable(folder)
                if exe: games.append(self._create_game_with_size(name, exe, LauncherType.STEAM, folder, game_id=appid or None))
        return games

    def _find_steam_roots(self, drives: List[str]) -> List[Path]:
        roots, seen = [], set()
        def add(p):
            if str(p).lower() not in seen: seen.add(str(p).lower()); roots.append(p)
        for d in drives:
            for r in self.LAUNCHER_PATHS[LauncherType.STEAM]:
                sd = Path(d) / r
                if sd.exists():
                    add(sd)
                    vdf = sd / "steamapps" / "libraryfolders.vdf"
                    if vdf.exists():
                        for lr in self._parse_steam_library_roots(vdf): add(lr)
        return roots

    def _parse_steam_library_roots(self, vdf_path: Path) -> List[Path]:
        roots = []
        try:
            for raw in re.findall(r'"path"\s+"([^"]+)"', vdf_path.read_text(encoding="utf-8", errors="ignore")):
                lib = Path(raw.replace("\\\\", "\\"))
                if lib.exists() and lib not in roots: roots.append(lib)
        except OSError: pass
        return roots

    @staticmethod
    def _parse_acf(acf_path: Path) -> dict:
        data = {}
        try:
            for k, v in re.findall(r'"(\w+)"\s+"([^"]*)"', acf_path.read_text(encoding="utf-8", errors="ignore")): data.setdefault(k, v)
        except OSError: pass
        return data

    def _scan_epic(self, launcher_type: LauncherType, drives: List[str]) -> List[Game]:
        games = []
        md = Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
        if md.exists():
            for item in md.glob("*.item"):
                try: data = json.loads(item.read_text(encoding="utf-8", errors="ignore"))
                except: continue
                name, loc, exe = data.get("DisplayName", "").strip(), data.get("InstallLocation", ""), data.get("LaunchExecutable", "")
                if not name or not loc or (data.get("MainGameAppName") and data.get("AppName") != data.get("MainGameAppName")): continue
                ip = Path(loc)
                if not ip.exists(): continue
                ep = ip / exe if exe and (ip / exe).exists() else self._find_executable(ip)
                if ep: games.append(self._create_game_with_size(name, ep, LauncherType.EPIC_GAMES, ip, launcher_id=data.get("AppName") or None))
        if not games: games = self._scan_epic_folders(drives)
        return games

    def _scan_epic_folders(self, drives: List[str]) -> List[Game]:
        games, seen = [], set()
        for d in drives:
            for r in self.LAUNCHER_PATHS[LauncherType.EPIC_GAMES]:
                b = Path(d) / r
                if not b.exists(): continue
                for gf in b.iterdir():
                    if not gf.is_dir() or gf.name.lower() in self.EPIC_SKIP_DIRS or str(gf).lower() in seen: continue
                    seen.add(str(gf).lower())
                    exe = self._find_executable(gf)
                    if exe: games.append(self._create_game_with_size(gf.name, exe, LauncherType.EPIC_GAMES, gf))
        return games

    def _scan_gog(self, launcher_type: LauncherType, drives: List[str]) -> List[Game]:
        games = []
        for hive, path in [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games"), (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\GOG.com\Games"), (winreg.HKEY_CURRENT_USER, r"SOFTWARE\GOG.com\Games")]:
            try: base = winreg.OpenKey(hive, path)
            except OSError: continue
            idx = 0
            while True:
                try: skn = winreg.EnumKey(base, idx); idx += 1
                except OSError: break
                try: sk = winreg.OpenKey(base, skn)
                except OSError: continue
                vals = {}
                v_idx = 0
                while True:
                    try: vn, vd, _ = winreg.EnumValue(sk, v_idx); v_idx += 1; vals[vn.lower()] = vd
                    except OSError: break
                winreg.CloseKey(sk)
                name, exe_raw, inst_raw, gid = (vals.get("gamename") or vals.get("name", "")).strip(), vals.get("gameexe") or vals.get("exe", ""), vals.get("path", ""), vals.get("gameid", "")
                if not name or not exe_raw: continue
                ep = Path(exe_raw)
                if not ep.exists(): continue
                games.append(self._create_game_with_size(name, ep, LauncherType.GOG_GALAXY, Path(inst_raw) if inst_raw else ep.parent, game_id=str(gid) or None))
            winreg.CloseKey(base)
        if not games: games = self._scan_folder_based(launcher_type, drives)
        return games

    def _scan_folder_based(self, launcher_type: LauncherType, drives: List[str]) -> List[Game]:
        games, seen = [], set()
        for d in drives:
            for r in self.LAUNCHER_PATHS.get(launcher_type, []):
                b = Path(d) / r
                if not b.exists(): continue
                sds = [b]
                if (b / "games").exists(): sds.append(b / "games")
                if (b / "content").exists(): sds.append(b / "content")
                for sd in sds:
                    try: entries = list(sd.iterdir())
                    except OSError: continue
                    for gf in entries:
                        if not gf.is_dir() or str(gf).lower() in seen: continue
                        seen.add(str(gf).lower())
                        exe = self._find_executable(gf)
                        if exe: games.append(self._create_game_with_size(gf.name, exe, launcher_type, gf))
        return games

    def _scan_itch(self, launcher_type: LauncherType, drives: List[str]) -> List[Game]:
        games = []
        ad = os.environ.get("APPDATA", "")
        if not ad: return games
        idir = Path(ad) / "itch" / "apps"
        if not idir.exists(): return games
        for gf in idir.iterdir():
            if not gf.is_dir(): continue
            exe = self._find_executable(gf)
            if exe: games.append(self._create_game_with_size(gf.name, exe, LauncherType.ITCH_IO, gf))
        return games

    def _find_executable(self, game_path: Path) -> Optional[Path]:
        if not game_path.exists(): return None
        fn = game_path.name.lower()
        cands = []
        try:
            cands.extend([f for f in game_path.glob("*.exe") if not self._is_skip_exe(f.name)])
            for e in game_path.rglob("*.exe"):
                if 0 < len(e.relative_to(game_path).parts) - 1 <= 3 and not self._is_skip_exe(e.name): cands.append(e)
        except (PermissionError, OSError): pass
        if not cands: return None
        for c in cands:
            s = c.stem.lower()
            if s == fn or fn in s or s in fn: return c
        shallow = [c for c in cands if len(c.relative_to(game_path).parts) - 1 <= 2]
        return max(shallow or cands, key=lambda f: f.stat().st_size)

    @classmethod
    def _is_skip_exe(cls, filename: str) -> bool:
        return any(w in filename.lower() for w in cls.SKIP_EXE_WORDS)

    def _save_detected_launchers(self, result: ScanResult, drives: List[str]):
        for lt in LauncherType:
            if lt in (LauncherType.UNKNOWN, LauncherType.STANDALONE): continue
            det, inst = False, None
            for d in drives:
                for r in self.LAUNCHER_PATHS.get(lt, []):
                    cp = Path(d) / r
                    if cp.exists(): det, inst = True, cp; break
                if det: break
            if lt == LauncherType.ITCH_IO:
                ad = os.environ.get("APPDATA", "")
                if ad and (Path(ad) / "itch").exists(): det, inst = True, Path(ad) / "itch"
            info = LauncherInfo(launcher_type=lt, name=lt.name.replace("_", " ").title(), install_path=inst, is_detected=det, game_count=len([g for g in result.games_found if g.launcher_type == lt]))
            self.db.save_launcher_info(info)
            result.launchers_detected.append(info)