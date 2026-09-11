import logging
import re
from dataclasses import dataclass, field, fields
from enum import Enum, auto
from pathlib import Path
from datetime import datetime
from typing import Optional, List


def normalize_name(text: str) -> str:
    """
    Normalisiert einen Namen für die Suche:
    Kleinbuchstaben, Umlaute ersetzt, Sonderzeichen zu Leerzeichen.
    """
    lower = text.lower()
    for source, target in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        lower = lower.replace(source, target)
    return re.sub(r"[^a-z0-9]+", " ", lower).strip()


class LauncherType(Enum):
    """Enum für alle unterstützten Launcher/Plattformen."""
    STEAM = auto()
    EPIC_GAMES = auto()
    GOG_GALAXY = auto()
    BATTLE_NET = auto()
    EA_APP = auto()
    UBISOFT = auto()
    XBOX = auto()
    RIOT = auto()
    GAIJIN = auto()
    AMAZON = auto()
    ITCH_IO = auto()
    STANDALONE = auto()
    UNKNOWN = auto()


@dataclass
class LauncherInfo:
    """Repräsentiert einen erkannten Launcher auf dem System."""
    launcher_type: LauncherType
    name: str
    install_path: Optional[Path] = None
    executable_path: Optional[Path] = None
    is_detected: bool = False
    game_count: int = 0

    @property
    def display_name(self) -> str:
        return self.name


@dataclass
class Game:
    """Repräsentiert ein einzelnes installiertes Spiel."""
    name: str
    executable_path: Path
    launcher_type: LauncherType

    game_id: Optional[str] = None
    install_path: Optional[Path] = None
    icon_path: Optional[Path] = None
    launch_arguments: str = ""
    launcher_id: Optional[str] = None

    last_played: Optional[datetime] = None
    total_playtime_minutes: int = 0
    is_favorite: bool = False
    is_hidden: bool = False

    date_added: datetime = field(default_factory=datetime.now)
    last_scanned: datetime = field(default_factory=datetime.now)

    @property
    def display_name(self) -> str:
        return self.name.strip()

    @property
    def launcher_display_name(self) -> str:
        launcher_names = {
            LauncherType.STEAM: "Steam",
            LauncherType.EPIC_GAMES: "Epic Games",
            LauncherType.GOG_GALAXY: "GOG Galaxy",
            LauncherType.BATTLE_NET: "Battle.net",
            LauncherType.EA_APP: "EA App",
            LauncherType.UBISOFT: "Ubisoft Connect",
            LauncherType.XBOX: "Xbox",
            LauncherType.RIOT: "Riot Games",
            LauncherType.GAIJIN: "Gaijin.net",
            LauncherType.AMAZON: "Amazon Games",
            LauncherType.ITCH_IO: "itch.io",
            LauncherType.STANDALONE: "Standalone",
            LauncherType.UNKNOWN: "Unbekannt",
        }
        return launcher_names.get(self.launcher_type, "Unbekannt")

    @property
    def playtime_display(self) -> str:
        """Sprachneutrale Spielzeit, z. B. '12 h 30 min'."""
        if self.total_playtime_minutes <= 0:
            return ""
        hours = self.total_playtime_minutes // 60
        minutes = self.total_playtime_minutes % 60
        if hours:
            return f"{hours} h {minutes} min"
        return f"{minutes} min"

    @property
    def last_played_display(self) -> str:
        """Nur das Datum (sprachneutral); leer, wenn nie gespielt."""
        if not self.last_played:
            return ""
        return f"{self.last_played:%d.%m.%Y}"

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "name": self.name,
            "executable_path": str(self.executable_path),
            "launcher_type": self.launcher_type.name,
            "install_path": str(self.install_path) if self.install_path else None,
            "icon_path": str(self.icon_path) if self.icon_path else None,
            "launch_arguments": self.launch_arguments,
            "launcher_id": self.launcher_id,
            "last_played": self.last_played.isoformat() if self.last_played else None,
            "total_playtime_minutes": self.total_playtime_minutes,
            "is_favorite": self.is_favorite,
            "is_hidden": self.is_hidden,
            "date_added": self.date_added.isoformat(),
            "last_scanned": self.last_scanned.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Game":
        """Robust gegen zusätzliche Schlüssel wie die interne DB-Spalte 'id'."""
        data = dict(data)

        valid_fields = {f.name for f in fields(cls)}
        unknown_keys = set(data) - valid_fields
        if unknown_keys:
            logging.debug(f"Game.from_dict: ignoriere unbekannte Felder {unknown_keys}")
            data = {k: v for k, v in data.items() if k in valid_fields}

        for key in ("executable_path", "install_path", "icon_path"):
            value = data.get(key)
            data[key] = Path(value) if value else None

        launcher_raw = data.get("launcher_type")
        if isinstance(launcher_raw, str):
            try:
                data["launcher_type"] = LauncherType[launcher_raw]
            except KeyError:
                logging.warning(f"Unbekannter Launcher-Typ '{launcher_raw}' → UNKNOWN")
                data["launcher_type"] = LauncherType.UNKNOWN

        for key in ("last_played", "date_added", "last_scanned"):
            value = data.get(key)
            if isinstance(value, str):
                try:
                    data[key] = datetime.fromisoformat(value)
                except ValueError:
                    data[key] = None if key == "last_played" else datetime.now()
            elif value is None and key != "last_played":
                data[key] = datetime.now()

        data["is_favorite"] = bool(data.get("is_favorite", 0))
        data["is_hidden"] = bool(data.get("is_hidden", 0))
        data["total_playtime_minutes"] = int(data.get("total_playtime_minutes", 0) or 0)

        return cls(**data)


@dataclass
class ScanResult:
    """Ergebnis eines vollständigen Scan-Durchlaufs."""
    games_found: List[Game] = field(default_factory=list)
    launchers_detected: List[LauncherInfo] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    scan_duration_seconds: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def total_games(self) -> int:
        return len(self.games_found)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0