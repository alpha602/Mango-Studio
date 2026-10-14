import logging
import subprocess
import time
import webbrowser
from datetime import datetime

from PySide6.QtCore import QObject, QThread, Signal

from data.database import Database
from data.models import Game, LauncherType

# Versteckt das Konsolenfenster bei tasklist-Aufrufen
CREATE_NO_WINDOW = 0x08000000


class _SessionMonitor(QThread):
    """
    Überwacht einen gestarteten Spielprozess im Hintergrund.
    Wartet interruptible (Polling), damit die App jederzeit sauber schließen kann.
    """
    session_finished = Signal(object, int)  # (Game, Minuten)

    def __init__(self, game: Game, process: subprocess.Popen, parent=None):
        super().__init__(parent)
        self._game = game
        self._process = process
        self._started_at = datetime.now()

    def run(self):
        try:
            while not self.isInterruptionRequested():
                if self._process.poll() is not None:
                    break
                self.msleep(300)

            if self.isInterruptionRequested():
                return

            minutes = int((datetime.now() - self._started_at).total_seconds() // 60)
            self.session_finished.emit(self._game, minutes)
        except Exception as e:
            logging.debug(f"Session-Monitor für '{self._game.name}' beendet: {e}")


class LauncherManager(QObject):
    """
    Zentrale Launcher-Bibliothek von Mango Studio.
    - Verwaltet Deep-Links & Startbefehle aller Launcher
    - Startet Spiele und überwacht direkte .exe-Sessions (Spielzeit-Tracking)
    - Erkennt laufende Launcher über die Windows-Prozessliste (gecasht)
    """
    game_launched = Signal(object)           # Game
    session_finished = Signal(object, int)   # Game, Minuten

    LAUNCHER_PROCESSES = {
        LauncherType.STEAM: ("steam.exe",),
        LauncherType.EPIC_GAMES: ("EpicGamesLauncher.exe",),
        LauncherType.GOG_GALAXY: ("GalaxyClient.exe",),
        LauncherType.BATTLE_NET: ("Battle.net.exe",),
        LauncherType.EA_APP: ("EADesktop.exe",),
        LauncherType.UBISOFT: ("UbisoftConnect.exe", "Upc.exe"),
        LauncherType.XBOX: ("XboxApp.exe",),
        LauncherType.RIOT: ("RiotClientServices.exe",),
        LauncherType.GAIJIN: ("wtlauncher.exe",),
        LauncherType.AMAZON: ("Amazon Games.exe",),
        LauncherType.ITCH_IO: ("itch.exe",),
    }

    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.db = database
        self._monitors: list = []
        self._running_cache: tuple = (0.0, set())

    # ─── Deep-Links & Startbefehle ────────────────────────────────────────

    def get_launch_command(self, game: Game) -> str:
        """
        Liefert den Startbefehl für ein Spiel.
        - Steam/Epic: Deep-Link (Launcher verwaltet DRM/Updates)
        - GOG: Deep-Link nur, wenn Galaxy läuft – sonst direkte .exe,
          damit unser Spielzeit-Tracking aktiv bleibt.
        - Sonst: direkter .exe-Pfad.
        """
        if game.launcher_type == LauncherType.STEAM and game.game_id:
            return f"steam://rungameid/{game.game_id}"
        if game.launcher_type == LauncherType.EPIC_GAMES and game.launcher_id:
            return f"com.epicgames.launcher://apps/{game.launcher_id}?action=launch"
        if game.launcher_type == LauncherType.GOG_GALAXY and game.game_id:
            if self.is_launcher_running(LauncherType.GOG_GALAXY):
                return f"galaxy://openGame/{game.game_id}"
        return str(game.executable_path)

    # ─── Start & Session-Tracking ─────────────────────────────────────────

    def launch_game(self, game: Game) -> bool:
        """Startet ein Spiel. Direkte .exe-Sessions werden überwacht."""
        command = self.get_launch_command(game)

        try:
            if "://" in command:
                webbrowser.open(command)
                self.db.record_play_session(game, 0)
                self.game_launched.emit(game)
                return True

            process = subprocess.Popen(
                [str(game.executable_path)] + game.launch_arguments.split(),
                cwd=str(game.executable_path.parent),
                creationflags=subprocess.DETACHED_PROCESS,
            )
            monitor = _SessionMonitor(game, process, parent=self)
            monitor.session_finished.connect(self._on_session_finished)
            monitor.finished.connect(lambda m=monitor: self._cleanup_monitor(m))
            self._monitors.append(monitor)
            monitor.start()

            self.game_launched.emit(game)
            return True

        except Exception as e:
            logging.error(f"Fehler beim Starten von '{game.name}': {e}", exc_info=True)
            return False

    def _on_session_finished(self, game: Game, minutes: int):
        self.db.record_play_session(game, minutes)
        logging.info(f"Session beendet: {game.name} (+{minutes} min)")
        self.session_finished.emit(game, minutes)

    def _cleanup_monitor(self, monitor: _SessionMonitor):
        if monitor in self._monitors:
            self._monitors.remove(monitor)

    def shutdown(self):
        """Beendet alle Session-Monitore sauber (wird beim App-Close aufgerufen)."""
        for monitor in list(self._monitors):
            monitor.requestInterruption()
        for monitor in list(self._monitors):
            monitor.wait(2000)
        self._monitors.clear()

    # ─── Launcher-Status (gecasht, 5 s TTL) ───────────────────────────────

    def get_running_launchers(self) -> set:
        now = time.monotonic()
        cached_at, cached_set = self._running_cache
        if now - cached_at < 5:
            return cached_set

        running = set()
        try:
            result = subprocess.run(
                ["tasklist", "/FO", "CSV"],
                capture_output=True,
                text=True,
                creationflags=CREATE_NO_WINDOW,
            )
            output = result.stdout.lower()
            for launcher_type, process_names in self.LAUNCHER_PROCESSES.items():
                if any(f'"{name.lower()}"' in output for name in process_names):
                    running.add(launcher_type)
        except Exception as e:
            logging.debug(f"tasklist nicht verfügbar: {e}")

        self._running_cache = (now, running)
        return running

    def is_launcher_running(self, launcher_type: LauncherType) -> bool:
        return launcher_type in self.get_running_launchers()