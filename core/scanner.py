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


BLACKLIST_SUBSTRINGS = (
    "epic online services", "steamworks", "source sdk", "sdk base",
    "redistributable", "directx", "vcredist", "vc_redist",
    "dedicated server", "unreal engine", "unity hub", "wallpaper engine",
    "game launcher", "steam client", "proton", "minecraft launcher",
    "epic games launcher", "riot client", "ubisoft connect",
    "gog galaxy", "wargaming game center", "xna framework",
)

BLACKLIST_REGEX = (
    r"^battle\.net[\s._-]*\d+$", r"^agent$", r"^blizzard$", r"^launcher$",
    r"^client$", r"^eos$", r"^redist$", r"^prerequisites$", r"^dotnet$",
    r"^games$", r"^shareplay$", r"^steam$", r"^common$",
)

_BLACKLIST_COMPILED = tuple(re.compile(p) for p in BLACKLIST_REGEX)


class ScanThread(QThread):
    """Führt einen Voll-Scan im Hintergrund aus (UI bleibt responsiv)."""
    scan_finished = Signal(object)  # ScanResult
    scan_error = Signal(str)

    def __init__(self, scanner: "Scanner", parent=None):
        super().__init__(parent)
        self._scanner = scanner

    def run(self):
        try:
            result = self._scanner.full_scan()
            self.scan_finished.emit(result)
        except Exception as e:
            logging.error(f"Scan-Thread fehlgeschlagen: {e}", exc_info=True)
            self.scan_error.emit(str(e))


class Scanner:
    """
    Scanner zum Auffinden installierter Spiele.
    Steam/Epic/GOG autoritativ, andere Launcher über Standardpfade,
    Standalone-Spiele über benutzerdefinierte Scan-Ordner (.exe-basiert).
    """

    LAUNCHER_PATHS = {
        LauncherType.STEAM: [
            "Program Files (x86)/Steam", "Program Files/Steam", "Steam",
        ],
        LauncherType.EPIC_GAMES: [
            "Program Files/Epic Games", "Program Files (x86)/Epic Games", "Epic Games",
        ],
        LauncherType.GOG_GALAXY: [
            "Program Files (x86)/GOG Galaxy/Games", "Program Files/GOG Galaxy/Games",
            "GOG Games", "Program Files (x86)/GOG Galaxy",
        ],
        LauncherType.BATTLE_NET: [
            "Program Files (x86)/Blizzard Entertainment",
            "Program Files/Blizzard Entertainment",
            "Program Files (x86)/Battle.net",
        ],
        LauncherType.EA_APP: [
            "Program Files/EA Games", "Program Files (x86)/EA Games",
            "Program Files (x86)/Origin Games", "Program Files/Origin Games",
        ],
        LauncherType.UBISOFT: [
            "Program Files (x86)/Ubisoft/Ubisoft Game Launcher/games",
            "Program Files/Ubisoft/Ubisoft Game Launcher/games",
            "Program Files (x86)/Ubisoft/Ubisoft Game Launcher",
        ],
        LauncherType.XBOX: ["XboxGames"],
        LauncherType.RIOT: ["Riot Games", "Program Files/Riot Games"],
        LauncherType.GAIJIN: ["Program Files (x86)/Gaijin", "Program Files/Gaijin"],
        LauncherType.AMAZON: ["Amazon Games", "Program Files/Amazon Games"],
        LauncherType.ITCH_IO: [],
        LauncherType.STANDALONE: [],
    }

    EPIC_SKIP_DIRS = {
        "launcher", "epic online services", "directxredist",
        "prerequisites", "eos", "epicgameslauncher",
    }

    SKIP_EXE_WORDS = (
        "uninstall", "unins", "setup", "redist", "vcredist", "directx",
        "crash", "anticheat", "easyanticheat", "beservice", "update",
        "patch", "installer", "config", "settings", "setupgame",
    )

    # Verzeichnisse, die beim Custom-Ordner-Scan übersprungen werden
    SKIP_DIR_NAMES = {
        "redist", "_commonredist", "commonredist", "directx", "vcredist",
        "prerequisites", "support", "dotnet", "webview", "mono", "sdk",
        "tools", "editor", "crashhandler", "anticheat",
    }

    def __init__(self, config: AppConfig, database: Database):
        self.config = config
        self.db = database

    # ─── Scan-Steuerung ───────────────────────────────────────────────────

    def should_perform_scan(self) -> bool:
        game_count = self.db.get_game_count()
        if game_count == 0:
            logging.warning("Datenbank ist leer – erster Start erkannt. "
                            "Automatischer Scan wird durchgeführt.")
            return True
        return False

    def full_scan(self) -> ScanResult:
        start_time = time.time()
        result = ScanResult()

        logging.warning("═══ Vollständiger Spiele-Scan gestartet ═══")

        drives = self._detect_available_drives()

        for launcher_type in LauncherType:
            if launcher_type == LauncherType.UNKNOWN:
                continue
            try:
                games = self._scan_launcher(launcher_type, drives)
                result.games_found.extend(games)
            except Exception as e:
                error_msg = f"Fehler beim Scannen von {launcher_type.name}: {e}"
                logging.error(error_msg)
                result.errors.append(error_msg)

        result.games_found = [
            g for g in result.games_found if not self._is_blacklisted(g.name)
        ]

        seen = set()
        unique_games = []
        for game in result.games_found:
            key = (game.name.lower(), game.launcher_type,
                   str(game.executable_path).lower())
            if key in seen:
                continue
            seen.add(key)
            unique_games.append(game)
        result.games_found = unique_games

        state_map = self.db.get_game_state_map()
        for game in result.games_found:
            key = (game.name.lower(), game.launcher_type.name,
                   str(game.executable_path).lower())
            hidden, favorite = state_map.get(key, (False, False))
            game.is_hidden = hidden
            game.is_favorite = favorite

        if result.games_found:
            self.db.clear_all_games()
            self.db.add_games_bulk(result.games_found)

        self._save_detected_launchers(result, drives)

        result.scan_duration_seconds = time.time() - start_time
        logging.warning(f"═══ Scan abgeschlossen in {result.scan_duration_seconds:.2f}s "
                        f"– {result.total_games} Spiele gefunden ═══")
        return result

    @staticmethod
    def _is_blacklisted(name: str) -> bool:
        lower = name.lower().strip()
        if any(token in lower for token in BLACKLIST_SUBSTRINGS):
            return True
        return any(pattern.match(lower) for pattern in _BLACKLIST_COMPILED)

    def _detect_available_drives(self) -> List[str]:
        drives = []
        for letter in string.ascii_uppercase:
            drive_path = f"{letter}:\\"
            try:
                if os.path.exists(drive_path):
                    drives.append(drive_path)
            except (PermissionError, OSError):
                pass
        return drives

    # ─── Routing ──────────────────────────────────────────────────────────

    def _scan_launcher(self, launcher_type: LauncherType, drives: List[str]) -> List[Game]:
        scanner_map = {
            LauncherType.STEAM: self._scan_steam,
            LauncherType.EPIC_GAMES: self._scan_epic,
            LauncherType.GOG_GALAXY: self._scan_gog,
            LauncherType.STANDALONE: self._scan_custom_folders,
            LauncherType.BATTLE_NET: self._scan_folder_based,
            LauncherType.EA_APP: self._scan_folder_based,
            LauncherType.UBISOFT: self._scan_folder_based,
            LauncherType.XBOX: self._scan_folder_based,
            LauncherType.RIOT: self._scan_folder_based,
            LauncherType.GAIJIN: self._scan_folder_based,
            LauncherType.AMAZON: self._scan_folder_based,
            LauncherType.ITCH_IO: self._scan_itch,
        }
        func = scanner_map.get(launcher_type)
        return func(launcher_type, drives) if func else []

    # ─── Benutzerdefinierte Scan-Ordner (.exe-basiert) ────────────────────

    def _scan_custom_folders(self, launcher_type: LauncherType, drives: List[str]) -> List[Game]:
        """
        Durchsucht die Config-Ordner rekursiv nach .exe-Dateien.
        - Junk-Exes (Update, Uninstall, Redist, ...) werden verworfen
        - Pro Unterordner wird nur die Haupt-.exe gewählt
          (Namens-Treffer zum Ordner > größte Datei)
        - Lose .exe-Dateien direkt im hinzugefügten Ordner = eigene Spiele
        """
        games = []
        seen_exes = set()

        for root_raw in self.config.custom_scan_folders:
            root = Path(root_raw)
            if not root.exists():
                continue

            groups: dict = {}
            try:
                for exe_file in root.rglob("*.exe"):
                    relative = exe_file.relative_to(root)
                    depth = len(relative.parts) - 1
                    if depth > 3:
                        continue
                    if self._is_skip_exe(exe_file.name):
                        continue
                    # Junk-Verzeichnisse überspringen
                    if any(part.lower() in self.SKIP_DIR_NAMES
                           for part in relative.parts[:-1]):
                        continue
                    groups.setdefault(exe_file.parent, []).append(exe_file)
            except (PermissionError, OSError):
                continue

            for directory, exes in groups.items():
                if directory == root:
                    # Lose Exes im Root: jede ist ein eigenes Spiel
                    chosen = exes
                else:
                    # Pro Unterordner nur die Haupt-.exe
                    chosen = [self._pick_main_exe(directory, exes)]

                for exe_file in chosen:
                    exe_key = str(exe_file).lower()
                    if exe_key in seen_exes:
                        continue
                    seen_exes.add(exe_key)

                    games.append(Game(
                        name=exe_file.stem,
                        executable_path=exe_file,
                        launcher_type=LauncherType.STANDALONE,
                        install_path=exe_file.parent,
                    ))
        return games

    @staticmethod
    def _pick_main_exe(directory: Path, exes: List[Path]) -> Path:
        """Wählt die wahrscheinlichste Haupt-.exe eines Ordners."""
        folder_name = directory.name.lower()
        for exe_file in exes:
            if exe_file.stem.lower() == folder_name:
                return exe_file
        for exe_file in exes:
            if folder_name in exe_file.stem.lower():
                return exe_file
        return max(exes, key=lambda f: f.stat().st_size)

    # ─── Steam ───────────────────────────────────────────────────────────

    def _scan_steam(self, launcher_type: LauncherType, drives: List[str]) -> List[Game]:
        games = []
        seen_folders = set()

        for steam_root in self._find_steam_roots(drives):
            steamapps = steam_root / "steamapps"
            if not steamapps.exists():
                continue

            for acf_file in steamapps.glob("appmanifest_*.acf"):
                meta = self._parse_acf(acf_file)
                appid = meta.get("appid", "")
                name = meta.get("name", "").strip()
                installdir = meta.get("installdir", "").strip()
                if not name or not installdir:
                    continue

                try:
                    state = int(meta.get("StateFlags", "0"))
                except ValueError:
                    state = 0
                if not (state & 4):
                    continue

                folder = steamapps / "common" / installdir
                folder_key = str(folder).lower()
                if not folder.exists() or folder_key in seen_folders:
                    continue
                seen_folders.add(folder_key)

                exe_path = self._find_executable(folder)
                if not exe_path:
                    continue

                games.append(Game(
                    name=name,
                    executable_path=exe_path,
                    launcher_type=LauncherType.STEAM,
                    install_path=folder,
                    game_id=appid or None,
                ))
        return games

    def _find_steam_roots(self, drives: List[str]) -> List[Path]:
        roots: List[Path] = []
        seen = set()

        def add_root(path: Path):
            key = str(path).lower()
            if key not in seen:
                seen.add(key)
                roots.append(path)

        for drive in drives:
            for rel_path in self.LAUNCHER_PATHS[LauncherType.STEAM]:
                steam_dir = Path(drive) / rel_path
                if not steam_dir.exists():
                    continue
                add_root(steam_dir)
                vdf_path = steam_dir / "steamapps" / "libraryfolders.vdf"
                if vdf_path.exists():
                    for lib_root in self._parse_steam_library_roots(vdf_path):
                        add_root(lib_root)
        return roots

    def _parse_steam_library_roots(self, vdf_path: Path) -> List[Path]:
        roots = []
        try:
            content = vdf_path.read_text(encoding="utf-8", errors="ignore")
            for raw_path in re.findall(r'"path"\s+"([^"]+)"', content):
                clean = raw_path.replace("\\\\", "\\")
                lib = Path(clean)
                if lib.exists() and lib not in roots:
                    roots.append(lib)
        except OSError as e:
            logging.debug(f"Konnte libraryfolders.vdf nicht lesen: {e}")
        return roots

    @staticmethod
    def _parse_acf(acf_path: Path) -> dict:
        data = {}
        try:
            text = acf_path.read_text(encoding="utf-8", errors="ignore")
            for key, value in re.findall(r'"(\w+)"\s+"([^"]*)"', text):
                data.setdefault(key, value)
        except OSError:
            pass
        return data

    # ─── Epic ─────────────────────────────────────────────────────────────

    def _scan_epic(self, launcher_type: LauncherType, drives: List[str]) -> List[Game]:
        games = []
        programdata = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
        manifest_dir = Path(programdata) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"

        if manifest_dir.exists():
            for item_file in manifest_dir.glob("*.item"):
                try:
                    data = json.loads(item_file.read_text(encoding="utf-8", errors="ignore"))
                except (json.JSONDecodeError, OSError):
                    continue

                name = (data.get("DisplayName") or "").strip()
                install_loc = data.get("InstallLocation") or ""
                launch_exe = data.get("LaunchExecutable") or ""
                if not name or not install_loc:
                    continue

                app_name = data.get("AppName") or ""
                main_app = data.get("MainGameAppName") or ""
                if main_app and app_name and main_app != app_name:
                    continue

                install_path = Path(install_loc)
                if not install_path.exists():
                    continue

                exe_path = None
                if launch_exe:
                    candidate = install_path / launch_exe
                    if candidate.exists():
                        exe_path = candidate
                if exe_path is None:
                    exe_path = self._find_executable(install_path)
                if exe_path is None:
                    continue

                games.append(Game(
                    name=name,
                    executable_path=exe_path,
                    launcher_type=LauncherType.EPIC_GAMES,
                    install_path=install_path,
                    launcher_id=app_name or None,
                ))

        if not games:
            games = self._scan_epic_folders(drives)
        return games

    def _scan_epic_folders(self, drives: List[str]) -> List[Game]:
        games = []
        seen_folders = set()
        for drive in drives:
            for rel_path in self.LAUNCHER_PATHS[LauncherType.EPIC_GAMES]:
                base_dir = Path(drive) / rel_path
                if not base_dir.exists():
                    continue
                for game_folder in base_dir.iterdir():
                    if not game_folder.is_dir():
                        continue
                    if game_folder.name.lower() in self.EPIC_SKIP_DIRS:
                        continue
                    folder_key = str(game_folder).lower()
                    if folder_key in seen_folders:
                        continue
                    seen_folders.add(folder_key)

                    exe_path = self._find_executable(game_folder)
                    if exe_path:
                        games.append(Game(
                            name=game_folder.name,
                            executable_path=exe_path,
                            launcher_type=LauncherType.EPIC_GAMES,
                            install_path=game_folder,
                        ))
        return games

    # ─── GOG ──────────────────────────────────────────────────────────────

    def _scan_gog(self, launcher_type: LauncherType, drives: List[str]) -> List[Game]:
        games = []
        reg_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\GOG.com\Games"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\GOG.com\Games"),
        ]
        for hive, path in reg_paths:
            try:
                base = winreg.OpenKey(hive, path)
            except OSError:
                continue

            index = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(base, index)
                    index += 1
                except OSError:
                    break
                try:
                    subkey = winreg.OpenKey(base, subkey_name)
                except OSError:
                    continue

                values = {}
                value_index = 0
                while True:
                    try:
                        value_name, value_data, _ = winreg.EnumValue(subkey, value_index)
                        value_index += 1
                    except OSError:
                        break
                    values[value_name.lower()] = value_data
                winreg.CloseKey(subkey)

                game_name = (values.get("gamename") or values.get("name") or "").strip()
                exe_raw = values.get("gameexe") or values.get("exe") or ""
                install_raw = values.get("path") or ""
                game_id_raw = values.get("gameid") or ""
                if not game_name or not exe_raw:
                    continue

                exe_path = Path(exe_raw)
                if not exe_path.exists():
                    continue

                games.append(Game(
                    name=game_name,
                    executable_path=exe_path,
                    launcher_type=LauncherType.GOG_GALAXY,
                    install_path=Path(install_raw) if install_raw else exe_path.parent,
                    game_id=str(game_id_raw) or None,
                ))
            winreg.CloseKey(base)

        if not games:
            games = self._scan_folder_based(launcher_type, drives)
        return games

    # ─── Generischer Ordner-Scan ──────────────────────────────────────────

    def _scan_folder_based(self, launcher_type: LauncherType, drives: List[str]) -> List[Game]:
        games = []
        seen_folders = set()

        for drive in drives:
            for rel_path in self.LAUNCHER_PATHS.get(launcher_type, []):
                base_dir = Path(drive) / rel_path
                if not base_dir.exists():
                    continue

                scan_dirs = [base_dir]
                games_subdir = base_dir / "games"
                if games_subdir.exists():
                    scan_dirs.append(games_subdir)
                content_subdir = base_dir / "content"
                if content_subdir.exists():
                    scan_dirs.append(content_subdir)

                for scan_dir in scan_dirs:
                    try:
                        entries = list(scan_dir.iterdir())
                    except OSError:
                        continue
                    for game_folder in entries:
                        if not game_folder.is_dir():
                            continue
                        folder_key = str(game_folder).lower()
                        if folder_key in seen_folders:
                            continue
                        seen_folders.add(folder_key)

                        exe_path = self._find_executable(game_folder)
                        if not exe_path:
                            continue

                        games.append(Game(
                            name=game_folder.name,
                            executable_path=exe_path,
                            launcher_type=launcher_type,
                            install_path=game_folder,
                        ))
        return games

    def _scan_itch(self, launcher_type: LauncherType, drives: List[str]) -> List[Game]:
        games = []
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            return games
        itch_dir = Path(appdata) / "itch" / "apps"
        if not itch_dir.exists():
            return games
        for game_folder in itch_dir.iterdir():
            if not game_folder.is_dir():
                continue
            exe_path = self._find_executable(game_folder)
            if exe_path:
                games.append(Game(
                    name=game_folder.name,
                    executable_path=exe_path,
                    launcher_type=LauncherType.ITCH_IO,
                    install_path=game_folder,
                ))
        return games

    # ─── Executable-Erkennung ─────────────────────────────────────────────

    def _find_executable(self, game_path: Path) -> Optional[Path]:
        if not game_path.exists():
            return None

        folder_name = game_path.name.lower()

        candidates: List[Path] = []
        try:
            root_exes = [f for f in game_path.glob("*.exe")
                         if not self._is_skip_exe(f.name)]
            candidates.extend(root_exes)

            for exe_file in game_path.rglob("*.exe"):
                depth = len(exe_file.relative_to(game_path).parts) - 1
                if depth == 0 or depth > 3:
                    continue
                if self._is_skip_exe(exe_file.name):
                    continue
                candidates.append(exe_file)
        except (PermissionError, OSError):
            pass

        if not candidates:
            return None

        for candidate in candidates:
            stem = candidate.stem.lower()
            if stem == folder_name or folder_name in stem or stem in folder_name:
                return candidate

        def depth_of(path: Path) -> int:
            return len(path.relative_to(game_path).parts) - 1

        shallow = [c for c in candidates if depth_of(c) <= 2]
        pool = shallow if shallow else candidates
        return max(pool, key=lambda f: f.stat().st_size)

    @classmethod
    def _is_skip_exe(cls, filename: str) -> bool:
        lower = filename.lower()
        return any(word in lower for word in cls.SKIP_EXE_WORDS)

    # ─── Launcher-Erkennung ───────────────────────────────────────────────

    def _save_detected_launchers(self, result: ScanResult, drives: List[str]):
        for launcher_type in LauncherType:
            if launcher_type in (LauncherType.UNKNOWN, LauncherType.STANDALONE):
                continue

            is_detected = False
            install_path = None
            for drive in drives:
                for rel_path in self.LAUNCHER_PATHS.get(launcher_type, []):
                    check_path = Path(drive) / rel_path
                    if check_path.exists():
                        is_detected = True
                        install_path = check_path
                        break
                if is_detected:
                    break

            if launcher_type == LauncherType.ITCH_IO:
                appdata = os.environ.get("APPDATA", "")
                if appdata:
                    itch_path = Path(appdata) / "itch"
                    if itch_path.exists():
                        is_detected = True
                        install_path = itch_path

            game_count = len([g for g in result.games_found
                              if g.launcher_type == launcher_type])

            launcher_info = LauncherInfo(
                launcher_type=launcher_type,
                name=launcher_type.name.replace("_", " ").title(),
                install_path=install_path,
                is_detected=is_detected,
                game_count=game_count,
            )
            self.db.save_launcher_info(launcher_info)
            result.launchers_detected.append(launcher_info)