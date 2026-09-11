import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.config import AppConfig
from data.models import Game, LauncherInfo, LauncherType


GAME_COLUMNS = (
    "game_id", "name", "executable_path", "launcher_type",
    "install_path", "icon_path", "launch_arguments", "launcher_id",
    "last_played", "total_playtime_minutes", "is_favorite",
    "is_hidden", "date_added", "last_scanned",
)
GAME_SELECT = ", ".join(GAME_COLUMNS)

GAME_INSERT_SQL = f"""
    INSERT OR REPLACE INTO games ({GAME_SELECT})
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

GAME_UPDATE_SET = """
    UPDATE games SET
        name = ?, executable_path = ?, launcher_type = ?,
        install_path = ?, icon_path = ?, launch_arguments = ?,
        launcher_id = ?, last_played = ?,
        total_playtime_minutes = ?, is_favorite = ?,
        is_hidden = ?, last_scanned = ?
"""

# Aktuelles Datenbankschema – für künftige Migrationen
CURRENT_SCHEMA_VERSION = 1


class Database:
    """Verwaltet die SQLite-Datenbank für Mango Studio."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.db_path = config.db_path
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_database(self):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # WAL-Modus: sicherer & schneller bei nebenläufigen Zugriffen
                cursor.execute("PRAGMA journal_mode=WAL")

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS games (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        game_id TEXT UNIQUE,
                        name TEXT NOT NULL,
                        executable_path TEXT NOT NULL,
                        launcher_type TEXT NOT NULL,
                        install_path TEXT,
                        icon_path TEXT,
                        launch_arguments TEXT DEFAULT '',
                        launcher_id TEXT,
                        last_played TEXT,
                        total_playtime_minutes INTEGER DEFAULT 0,
                        is_favorite INTEGER DEFAULT 0,
                        is_hidden INTEGER DEFAULT 0,
                        date_added TEXT NOT NULL,
                        last_scanned TEXT NOT NULL
                    )
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS launchers (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        launcher_type TEXT UNIQUE NOT NULL,
                        name TEXT NOT NULL,
                        install_path TEXT,
                        executable_path TEXT,
                        is_detected INTEGER DEFAULT 0,
                        game_count INTEGER DEFAULT 0
                    )
                """)

                # Schema-Versionsverwaltung für künftige Migrationen
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS schema_version (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )
                """)
                cursor.execute("SELECT COUNT(*) FROM schema_version")
                if cursor.fetchone()[0] == 0:
                    cursor.execute(
                        "INSERT INTO schema_version (version, applied_at) VALUES (1, ?)",
                        (datetime.now().isoformat(),),
                    )

                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_games_name
                    ON games(name COLLATE NOCASE)
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_games_launcher
                    ON games(launcher_type)
                """)

                conn.commit()
                logging.info(f"Datenbank initialisiert: {self.db_path}")

        except sqlite3.Error as e:
            logging.error(f"Fehler beim Initialisieren der Datenbank: {e}")
            raise

    # ─── Interne Helfer ───────────────────────────────────────────────────

    @staticmethod
    def _row_to_game(row: sqlite3.Row) -> Game:
        return Game.from_dict(dict(row))

    @staticmethod
    def _game_params(game: Game) -> tuple:
        data = game.to_dict()
        return (
            data["game_id"],
            data["name"],
            data["executable_path"],
            data["launcher_type"],
            data["install_path"],
            data["icon_path"],
            data["launch_arguments"],
            data["launcher_id"],
            data["last_played"],
            data["total_playtime_minutes"],
            int(data["is_favorite"]),
            int(data["is_hidden"]),
            data["date_added"],
            data["last_scanned"],
        )

    # ─── Spiele-Operationen ───────────────────────────────────────────────

    def add_game(self, game: Game) -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute(GAME_INSERT_SQL, self._game_params(game))
                conn.commit()
                return True
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Hinzufügen des Spiels '{game.name}': {e}")
            return False

    def add_games_bulk(self, games: List[Game]) -> int:
        success_count = 0
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                for game in games:
                    try:
                        cursor.execute(GAME_INSERT_SQL, self._game_params(game))
                        success_count += 1
                    except sqlite3.Error as e:
                        logging.warning(f"Übersprungen '{game.name}': {e}")
                conn.commit()
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Bulk-Insert: {e}")
        return success_count

    def get_all_games(self, include_hidden: bool = False) -> List[Game]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if include_hidden:
                    sql = f"SELECT {GAME_SELECT} FROM games ORDER BY name COLLATE NOCASE"
                    cursor.execute(sql)
                else:
                    sql = (f"SELECT {GAME_SELECT} FROM games "
                           f"WHERE is_hidden = 0 ORDER BY name COLLATE NOCASE")
                    cursor.execute(sql)
                return [self._row_to_game(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Laden aller Spiele: {e}")
            return []

    def search_games(self, query: str) -> List[Game]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT {GAME_SELECT} FROM games "
                    f"WHERE name LIKE ? COLLATE NOCASE AND is_hidden = 0 "
                    f"ORDER BY name COLLATE NOCASE",
                    (f"%{query}%",),
                )
                return [self._row_to_game(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logging.error(f"Fehler bei der Spielsuche '{query}': {e}")
            return []

    def get_games_by_launcher(self, launcher_type: LauncherType) -> List[Game]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT {GAME_SELECT} FROM games "
                    f"WHERE launcher_type = ? AND is_hidden = 0 "
                    f"ORDER BY name COLLATE NOCASE",
                    (launcher_type.name,),
                )
                return [self._row_to_game(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Laden der Spiele für {launcher_type.name}: {e}")
            return []

    def get_game_by_id(self, game_id: str) -> Optional[Game]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT {GAME_SELECT} FROM games WHERE game_id = ?",
                    (game_id,),
                )
                row = cursor.fetchone()
                return self._row_to_game(row) if row else None
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Laden des Spiels mit ID '{game_id}': {e}")
            return None

    def update_game(self, game: Game) -> bool:
        """
        Aktualisiert ein Spiel. Matcht primär über game_id,
        mit Fallback über Name + Launcher + Exe-Pfad (für Spiele ohne ID).
        """
        params = (
            game.name,
            str(game.executable_path),
            game.launcher_type.name,
            str(game.install_path) if game.install_path else None,
            str(game.icon_path) if game.icon_path else None,
            game.launch_arguments,
            game.launcher_id,
            game.last_played.isoformat() if game.last_played else None,
            game.total_playtime_minutes,
            int(game.is_favorite),
            int(game.is_hidden),
            game.last_scanned.isoformat(),
        )
        if game.game_id:
            where = " WHERE game_id = ?"
            where_params = (game.game_id,)
        else:
            where = " WHERE name = ? AND launcher_type = ? AND executable_path = ?"
            where_params = (game.name, game.launcher_type.name, str(game.executable_path))

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(GAME_UPDATE_SET + where, params + where_params)
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Aktualisieren des Spiels '{game.name}': {e}")
            return False

    def delete_game(self, game_id: str) -> bool:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM games WHERE game_id = ?", (game_id,))
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Löschen des Spiels mit ID '{game_id}': {e}")
            return False

    def clear_all_games(self) -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM games")
                conn.commit()
                return True
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Löschen aller Spiele: {e}")
            return False

    def set_game_hidden(self, game: Game, hidden: bool) -> bool:
        """Verbirgt ein Spiel oder zeigt es wieder an."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE games SET is_hidden = ? "
                    "WHERE name = ? AND launcher_type = ? AND executable_path = ?",
                    (int(hidden), game.name, game.launcher_type.name,
                     str(game.executable_path)),
                )
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Verbergen/Sichtbarmachen von '{game.name}': {e}")
            return False

    def set_game_favorite(self, game: Game, favorite: bool) -> bool:
        """Markiert ein Spiel als Favorit oder entfernt die Markierung."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE games SET is_favorite = ? "
                    "WHERE name = ? AND launcher_type = ? AND executable_path = ?",
                    (int(favorite), game.name, game.launcher_type.name,
                     str(game.executable_path)),
                )
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Favorisieren von '{game.name}': {e}")
            return False

    def record_play_session(self, game: Game, minutes: int) -> bool:
        """Setzt 'last_played' und addiert die Minuten zur Gesamtspielzeit."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE games SET last_played = ?, "
                    "total_playtime_minutes = total_playtime_minutes + ? "
                    "WHERE name = ? AND launcher_type = ? AND executable_path = ?",
                    (datetime.now().isoformat(), int(minutes),
                     game.name, game.launcher_type.name, str(game.executable_path)),
                )
                conn.commit()
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Speichern der Session von '{game.name}': {e}")
            return False

    def get_game_state_map(self) -> dict:
        """Liefert (name, launcher, exe) -> (is_hidden, is_favorite) für Rescans."""
        state_map = {}
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name, launcher_type, executable_path, "
                    "is_hidden, is_favorite FROM games"
                )
                for row in cursor.fetchall():
                    key = (
                        row["name"].lower(),
                        row["launcher_type"],
                        row["executable_path"].lower(),
                    )
                    state_map[key] = (bool(row["is_hidden"]), bool(row["is_favorite"]))
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Laden des Spiel-Status: {e}")
        return state_map

    # ─── Launcher-Operationen ─────────────────────────────────────────────

    def save_launcher_info(self, launcher: LauncherInfo) -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO launchers (
                        launcher_type, name, install_path,
                        executable_path, is_detected, game_count
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    launcher.launcher_type.name,
                    launcher.name,
                    str(launcher.install_path) if launcher.install_path else None,
                    str(launcher.executable_path) if launcher.executable_path else None,
                    int(launcher.is_detected),
                    launcher.game_count,
                ))
                conn.commit()
                return True
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Speichern des Launchers '{launcher.name}': {e}")
            return False

    def get_all_launchers(self) -> List[LauncherInfo]:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM launchers")
                launchers = []
                for row in cursor.fetchall():
                    launchers.append(LauncherInfo(
                        launcher_type=LauncherType[row["launcher_type"]],
                        name=row["name"],
                        install_path=Path(row["install_path"]) if row["install_path"] else None,
                        executable_path=Path(row["executable_path"]) if row["executable_path"] else None,
                        is_detected=bool(row["is_detected"]),
                        game_count=row["game_count"],
                    ))
                return launchers
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Laden der Launcher: {e}")
            return []

    # ─── Statistiken ──────────────────────────────────────────────────────

    def get_game_count(self) -> int:
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM games WHERE is_hidden = 0")
                return cursor.fetchone()[0]
        except sqlite3.Error as e:
            logging.error(f"Fehler beim Zählen der Spiele: {e}")
            return 0