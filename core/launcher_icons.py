import ctypes
import logging
import os
import string
from ctypes import wintypes
from pathlib import Path
from typing import Optional, List

from PySide6.QtCore import QSize, Qt, QFileInfo
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QBrush
from PySide6.QtWidgets import QFileIconProvider

from core.config import AppConfig
from data.models import LauncherType


class LauncherIconProvider:
    """
    Liefert runde Launcher-Logos für die Kachel-Overlays.
    Quellen-Priorität:
      1. RAM-Cache → 2. Festplatten-Cache
      3. QFileIconProvider auf der Launcher-.exe (pure Qt, sehr zuverlässig)
      4. PrivateExtractIconsW (Windows-API)
      5. Fallback: farbiger Kreis mit Initial
    Launcher-.exe-Pfade kommen aus der Datenbank (Scanner-Erkennung),
    aus hart kodierten Standardpfaden und aus Glob-Patterns.
    """

    SIZE = QSize(32, 32)
    CACHE_VERSION = "v2"   # Neue Revision: alte Caches werden ignoriert

    LAUNCHER_EXE_CANDIDATES = {
        LauncherType.STEAM: (
            "Program Files (x86)/Steam/steam.exe",
            "Program Files/Steam/steam.exe",
            "Steam/steam.exe",
        ),
        LauncherType.EPIC_GAMES: (
            "Program Files/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe",
            "Program Files (x86)/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe",
            "Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe",
        ),
        LauncherType.GOG_GALAXY: (
            "Program Files (x86)/GOG Galaxy/GalaxyClient.exe",
            "Program Files/GOG Galaxy/GalaxyClient.exe",
            "GOG Galaxy/GalaxyClient.exe",
        ),
        LauncherType.BATTLE_NET: (
            "Program Files (x86)/Battle.net/Battle.net.exe",
            "Program Files/Battle.net/Battle.net.exe",
            "Battle.net/Battle.net.exe",
        ),
        LauncherType.EA_APP: (
            "Program Files/Electronic Arts/EA Desktop/EA Desktop/EADesktop.exe",
            "Program Files/EA Games/EA Desktop/EADesktop.exe",
            "Program Files (x86)/Origin/Origin.exe",
        ),
        LauncherType.UBISOFT: (
            "Program Files (x86)/Ubisoft/Ubisoft Game Launcher/UbisoftConnect.exe",
            "Program Files/Ubisoft/Ubisoft Game Launcher/UbisoftConnect.exe",
        ),
        LauncherType.RIOT: (
            "Riot Games/Riot Client/RiotClientServices.exe",
            "Program Files/Riot Games/Riot Client/RiotClientServices.exe",
        ),
        LauncherType.GAIJIN: (
            "Program Files (x86)/Gaijin/wtlauncher.exe",
            "Gaijin/wtlauncher.exe",
        ),
        LauncherType.AMAZON: (
            "Amazon Games/Amazon Games.exe",
            "Program Files/Amazon Games/Amazon Games.exe",
        ),
    }

    # Glob-Patterns für abweichende Installationswurzeln (pro Laufwerk)
    LAUNCHER_EXE_GLOBS = {
        LauncherType.STEAM: ("*/Steam/steam.exe",),
        LauncherType.EPIC_GAMES: ("*/Epic Games/Launcher/Portal/Binaries/Win64/EpicGamesLauncher.exe",),
        LauncherType.GOG_GALAXY: ("*/GOG Galaxy/GalaxyClient.exe",),
        LauncherType.BATTLE_NET: ("*/Battle.net/Battle.net.exe",),
        LauncherType.UBISOFT: ("*/Ubisoft/Ubisoft Game Launcher/UbisoftConnect.exe",),
    }

    COLORS = {
        LauncherType.STEAM: "#66c0f4",
        LauncherType.EPIC_GAMES: "#b8b8b8",
        LauncherType.GOG_GALAXY: "#a155c1",
        LauncherType.BATTLE_NET: "#0074e0",
        LauncherType.EA_APP: "#ff4747",
        LauncherType.UBISOFT: "#4b69ff",
        LauncherType.XBOX: "#107c10",
        LauncherType.RIOT: "#eb2350",
        LauncherType.GAIJIN: "#ffcc00",
        LauncherType.AMAZON: "#ff9900",
        LauncherType.ITCH_IO: "#fa5c5c",
        LauncherType.STANDALONE: "#8a8aa8",
        LauncherType.UNKNOWN: "#555566",
    }

    def __init__(self, config: AppConfig, database=None):
        self.config = config
        self.db = database
        self.cache_dir = config.base_dir / "cache" / "launchers"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: dict = {}
        self._warned: set = set()
        self._file_icon_provider = QFileIconProvider()

    # ─── Öffentliche API ──────────────────────────────────────────────────

    def get_icon(self, launcher_type: LauncherType) -> QImage:
        """Gibt das runde Launcher-Icon zurück (gecasht)."""
        if launcher_type in self._memory_cache:
            return self._memory_cache[launcher_type]

        disk_path = self.cache_dir / f"{launcher_type.name}_{self.CACHE_VERSION}.png"
        if disk_path.exists():
            image = QImage(str(disk_path))
            if not image.isNull():
                self._memory_cache[launcher_type] = image
                return image

        image = self._load_icon(launcher_type)
        if image is None or image.isNull():
            if launcher_type not in self._warned:
                self._warned.add(launcher_type)
                logging.warning(
                    f"Launcher-Icon für {launcher_type.name} nicht gefunden – "
                    f"Fallback wird verwendet."
                )
            image = self._create_fallback_icon(launcher_type)
        else:
            image = self._make_round(image)
            image.save(str(disk_path), "PNG")

        self._memory_cache[launcher_type] = image
        return image

    # ─── Icon-Suche ───────────────────────────────────────────────────────

    def _load_icon(self, launcher_type: LauncherType) -> Optional[QImage]:
        for exe_path in self._find_launcher_exes(launcher_type):
            image = self._icon_from_exe(exe_path)
            if image is not None:
                return image
        return None

    def _find_launcher_exes(self, launcher_type: LauncherType) -> List[Path]:
        """Sammelt Kandidaten-Pfade für die Launcher-.exe (DB → Standard → Glob)."""
        results: List[Path] = []
        seen = set()

        def add_candidate(path: Path):
            key = str(path).lower()
            if key in seen:
                return
            seen.add(key)
            results.append(path)

        # 1) Vom Scanner erkannte Pfade aus der Datenbank
        if self.db is not None:
            try:
                for info in self.db.get_all_launchers():
                    if info.launcher_type != launcher_type or not info.is_detected:
                        continue
                    if info.executable_path:
                        add_candidate(Path(info.executable_path))
                    if info.install_path:
                        install = Path(info.install_path)
                        if install.suffix.lower() == ".exe":
                            add_candidate(install)
                        elif install.exists():
                            root_exes = sorted(
                                install.glob("*.exe"),
                                key=lambda f: f.stat().st_size,
                                reverse=True,
                            )
                            for exe in root_exes[:3]:
                                add_candidate(exe)
            except Exception as e:
                logging.debug(f"DB-Launcher-Pfade nicht lesbar: {e}")

        # 2) Hart kodierte Standardpfade auf allen Laufwerken
        for drive in self._available_drives():
            for rel_path in self.LAUNCHER_EXE_CANDIDATES.get(launcher_type, ()):
                add_candidate(Path(drive) / rel_path)

        # 3) Glob-Patterns für abweichende Wurzeln (eine Ebene tiefer)
        for drive in self._available_drives():
            for pattern in self.LAUNCHER_EXE_GLOBS.get(launcher_type, ()):
                try:
                    for match in Path(drive).glob(pattern):
                        add_candidate(match)
                except OSError:
                    continue

        return [p for p in results if p.exists() and p.suffix.lower() == ".exe"]

    def _icon_from_exe(self, exe_path: Path) -> Optional[QImage]:
        """Extrahiert das eingebettete Icon einer .exe (zwei Strategien)."""
        # A) QFileIconProvider – pure Qt, zuverlässig auf Windows
        try:
            icon = self._file_icon_provider.icon(QFileInfo(str(exe_path)))
            sizes = icon.availableSizes()
            if sizes:
                native = max(sizes, key=lambda s: s.width())
                pixmap = icon.pixmap(native)
            else:
                pixmap = icon.pixmap(48, 48)
            if not pixmap.isNull() and max(pixmap.width(), pixmap.height()) >= 24:
                image = pixmap.toImage()
                if not image.isNull():
                    return image
        except Exception as e:
            logging.debug(f"QFileIconProvider fehlgeschlagen ({exe_path}): {e}")

        # B) Windows-API PrivateExtractIconsW
        if hasattr(QImage, "fromHICON"):
            try:
                hicon = wintypes.HICON()
                icon_id = wintypes.UINT()
                count = ctypes.windll.user32.PrivateExtractIconsW(
                    str(exe_path), 0, 64, 64,
                    ctypes.byref(hicon), ctypes.byref(icon_id), 1, 0,
                )
                if count > 0 and hicon:
                    image = QImage.fromHICON(hicon)
                    ctypes.windll.user32.DestroyIcon(hicon)
                    if not image.isNull():
                        return image
            except Exception as e:
                logging.debug(f"PrivateExtractIcons fehlgeschlagen ({exe_path}): {e}")

        return None

    # ─── Aufbereitung ─────────────────────────────────────────────────────

    def _make_round(self, image: QImage) -> QImage:
        """Schneidet quadratisch zu und zeichnet das Icon als Kreis."""
        scaled = image.scaled(self.SIZE, Qt.KeepAspectRatioByExpanding,
                              Qt.SmoothTransformation)
        x = (scaled.width() - self.SIZE.width()) // 2
        y = (scaled.height() - self.SIZE.height()) // 2
        cropped = scaled.copy(x, y, self.SIZE.width(), self.SIZE.height())

        canvas = QImage(self.SIZE, QImage.Format_ARGB32)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(cropped))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(canvas.rect(), 16, 16)
        painter.end()
        return canvas

    def _create_fallback_icon(self, launcher_type: LauncherType) -> QImage:
        """Farbiger Kreis mit Initial als letzter Fallback."""
        canvas = QImage(self.SIZE, QImage.Format_ARGB32)
        canvas.fill(Qt.transparent)

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(self.COLORS.get(launcher_type, "#8a8aa8"))
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(canvas.rect())

        letter = launcher_type.name[0].upper()
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 16, QFont.Bold))
        painter.drawText(canvas.rect(), Qt.AlignCenter, letter)
        painter.end()
        return canvas

    @staticmethod
    def _available_drives() -> List[str]:
        drives = []
        for letter in string.ascii_uppercase:
            if os.path.exists(f"{letter}:\\"):
                drives.append(f"{letter}:\\")
        return drives