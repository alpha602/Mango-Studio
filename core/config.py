import os
import json
import platform
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from PySide6.QtCore import QSize, QPoint


@dataclass
class AppConfig:
    """
    Zentrale Konfiguration der Mango Studio App.
    Verwaltet Pfade, UI-Einstellungen, Sprache und benutzerdefinierte Scan-Ordner.
    Alles persistent in settings.json.
    """
    APP_NAME: str = "Mango Studio"
    APP_VERSION: str = "1.0.0"
    ORGANIZATION: str = "Mango Studio"

    # UI-Einstellungen
    window_size: QSize = field(default_factory=lambda: QSize(1200, 800))
    window_pos: QPoint = field(default_factory=lambda: QPoint(100, 100))
    theme: str = "system"
    language: str = "de"
    minimize_to_tray: bool = False

    # Benutzerdefinierte Scan-Ordner (Standalone-Spiele)
    custom_scan_folders: List[str] = field(default_factory=list)

    # Pfade
    base_dir: Path = field(init=False, repr=False)
    data_dir: Path = field(init=False, repr=False)
    db_path: Path = field(init=False, repr=False)
    settings_path: Path = field(init=False, repr=False)

    def __post_init__(self):
        self._setup_paths()
        self.load_settings()

    def _setup_paths(self):
        if platform.system() == "Windows":
            appdata = os.environ.get("APPDATA")
            base_path = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        else:
            base_path = Path.home() / ".local" / "share"

        self.base_dir = base_path / self.APP_NAME
        self.data_dir = self.base_dir / "data"
        self.settings_path = self.base_dir / "settings.json"

        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = self.data_dir / "mango_games.db"
        except OSError as e:
            logging.error(f"Fehler beim Erstellen der App-Verzeichnisse: {e}")
            self.base_dir = Path.cwd()
            self.data_dir = self.base_dir / "data"
            self.data_dir.mkdir(exist_ok=True)
            self.db_path = self.data_dir / "mango_games.db"
            self.settings_path = self.base_dir / "settings.json"

    def load_settings(self):
        """Lädt persistente Einstellungen."""
        if not self.settings_path.exists():
            return
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))

            width = int(data.get("window_width", 0))
            height = int(data.get("window_height", 0))
            if width >= 800 and height >= 500:
                self.window_size = QSize(width, height)

            x = data.get("window_x")
            y = data.get("window_y")
            if isinstance(x, int) and isinstance(y, int):
                self.window_pos = QPoint(x, y)

            if isinstance(data.get("theme"), str):
                self.theme = data["theme"]
            if isinstance(data.get("language"), str):
                self.language = data["language"]
            if isinstance(data.get("minimize_to_tray"), bool):
                self.minimize_to_tray = data["minimize_to_tray"]

            folders = data.get("custom_scan_folders")
            if isinstance(folders, list):
                self.custom_scan_folders = [f for f in folders if isinstance(f, str)]
        except (json.JSONDecodeError, OSError, ValueError) as e:
            logging.warning(f"Einstellungen konnten nicht geladen werden: {e}")

    def save_settings(self):
        """Speichert die aktuellen Einstellungen persistent."""
        try:
            data = {
                "window_width": self.window_size.width(),
                "window_height": self.window_size.height(),
                "window_x": self.window_pos.x(),
                "window_y": self.window_pos.y(),
                "theme": self.theme,
                "language": self.language,
                "minimize_to_tray": self.minimize_to_tray,
                "custom_scan_folders": self.custom_scan_folders,
            }
            self.settings_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
        except OSError as e:
            logging.error(f"Einstellungen konnten nicht gespeichert werden: {e}")