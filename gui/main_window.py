import os
import logging
import subprocess
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QGridLayout, QFrame,
    QMessageBox, QApplication, QMenu, QLabel, QSystemTrayIcon
)
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QFont, QIcon

from core.config import AppConfig
from core.scanner import Scanner, ScanThread
from core.icon_loader import IconLoader
from core.launcher_icons import LauncherIconProvider
from core.launchers import LauncherManager
from core.i18n import tr, set_language
from data.database import Database
from data.models import Game, LauncherType, ScanResult, normalize_name
from gui.game_card import GameCard
from gui.settings_dialog import SettingsDialog
from gui.widgets import (
    SearchBar, PrimaryButton, EmptyPlaceholder, LauncherFilterBar
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STYLES_PATH = PROJECT_ROOT / "assets" / "styles" / "main.qss"
WINDOW_ICON_CANDIDATES = [
    PROJECT_ROOT / "assets" / "icons" / "mango.ico",
    PROJECT_ROOT / "assets" / "icons" / "mango.png",
]


class MainWindow(QMainWindow):
    """
    Hauptfenster: Suche, Filter, Settings-Button, Cover-Grid mit
    Favoriten-Sektion, Kontextmenü, Tray und Launcher-Verwaltung.
    """

    def __init__(self, config: AppConfig, force_rescan: bool = False):
        super().__init__()
        self.config = config
        self._force_rescan = force_rescan
        self._really_quit = False
        set_language(config.language)

        self.resize(self.config.window_size)
        self.move(self.config.window_pos)

        # Kern-Module
        self.db = Database(self.config)
        self.scanner = Scanner(self.config, self.db)
        self.icon_loader = IconLoader(self.config)
        # WICHTIG: Datenbank mitgeben, damit der Provider erkannte
        # Launcher-Pfade für die echten Logos nutzen kann
        self.launcher_icons = LauncherIconProvider(self.config, self.db)
        self.launcher_manager = LauncherManager(self.db, parent=self)

        self.launcher_manager.game_launched.connect(self._on_game_launched)
        self.launcher_manager.session_finished.connect(self._on_session_finished)

        # Zustand
        self.all_games: list = []
        self._current_games: list = []
        self._current_columns = 0
        self._last_grid_width = 0
        self._grid_initialized = False
        self._launcher_filter: LauncherType = None
        self._scan_thread: ScanThread = None
        self.tray_icon: QSystemTrayIcon = None

        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self._apply_filters)

        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)
        self._resize_timer.timeout.connect(self._rebuild_grid)

        self._apply_stylesheet()
        self._apply_window_icon()
        self._init_ui()
        self._setup_tray()

    # ─── Design & UI ──────────────────────────────────────────────────────

    def _apply_stylesheet(self):
        if STYLES_PATH.exists():
            QApplication.instance().setStyleSheet(STYLES_PATH.read_text(encoding="utf-8"))
        else:
            logging.warning(f"Stylesheet NICHT gefunden: {STYLES_PATH}")

    def _apply_window_icon(self):
        for candidate in WINDOW_ICON_CANDIDATES:
            if candidate.exists():
                self.setWindowIcon(QIcon(str(candidate)))
                return

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._create_header(main_layout)
        self._create_status_bar(main_layout)
        self._create_filter_bar(main_layout)
        self._create_content_area(main_layout)
        self.retranslate_ui()

    def _create_header(self, layout: QVBoxLayout):
        header_widget = QWidget()
        header_widget.setObjectName("header_widget")
        header_widget.setAttribute(Qt.WA_StyledBackground, True)
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(30, 20, 30, 10)
        header_layout.setSpacing(12)

        title_row = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setObjectName("app_title")
        self.title_label.setFont(QFont("Segoe UI", 26, QFont.Bold))

        self.refresh_button = PrimaryButton("")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)

        self.settings_button = PrimaryButton("")
        self.settings_button.setObjectName("settings_button")
        self.settings_button.clicked.connect(self._open_settings)

        title_row.addWidget(self.title_label)
        title_row.addStretch()
        title_row.addWidget(self.settings_button)
        title_row.addWidget(self.refresh_button)

        self.search_input = SearchBar()
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.returnPressed.connect(self._on_search_return_pressed)

        header_layout.addLayout(title_row)
        header_layout.addWidget(self.search_input)
        layout.addWidget(header_widget)

    def _create_status_bar(self, layout: QVBoxLayout):
        self.status_widget = QWidget()
        self.status_widget.setObjectName("status_widget")
        self.status_widget.setAttribute(Qt.WA_StyledBackground, True)
        status_layout = QHBoxLayout(self.status_widget)
        status_layout.setContentsMargins(30, 8, 30, 8)

        self.status_label = QLabel()
        self.status_label.setObjectName("status_label")

        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        layout.addWidget(self.status_widget)

    def _create_filter_bar(self, layout: QVBoxLayout):
        self.filter_bar = LauncherFilterBar()
        self.filter_bar.filter_changed.connect(self._on_launcher_filter_changed)
        layout.addWidget(self.filter_bar)

    def _create_content_area(self, layout: QVBoxLayout):
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("game_scroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)

        self.games_container = QWidget()
        self.games_container.setObjectName("games_container")
        self.games_container.setAttribute(Qt.WA_StyledBackground, True)
        self.games_layout = QGridLayout(self.games_container)
        self.games_layout.setSpacing(16)
        self.games_layout.setContentsMargins(30, 20, 30, 30)

        self.scroll_area.setWidget(self.games_container)
        layout.addWidget(self.scroll_area)

    # ─── Übersetzung ──────────────────────────────────────────────────────

    def retranslate_ui(self):
        """Setzt alle statischen UI-Texte neu (nach Sprachwechsel)."""
        self.setWindowTitle(f"{tr('app.title')} - {tr('app.subtitle')}")
        self.title_label.setText(f"🥭 {tr('app.title')}")
        self.refresh_button.setText(tr("button.refresh"))
        self.settings_button.setText(tr("button.settings"))
        self.search_input.retranslate()
        if self.tray_icon is not None:
            self.tray_icon.setToolTip(tr("app.title"))
            self.tray_action_show.setText(tr("tray.show"))
            self.tray_action_scan.setText(tr("tray.scan"))
            self.tray_action_quit.setText(tr("tray.quit"))
        self._apply_filters()

    # ─── Settings & Tray ──────────────────────────────────────────────────

    def _open_settings(self):
        dialog = SettingsDialog(self.config, self.db, parent=self)
        dialog.settings_changed.connect(self._on_settings_changed)
        dialog.rescan_requested.connect(self._perform_scan)
        dialog.exec()

    def _on_settings_changed(self):
        self.retranslate_ui()
        self._load_games_from_db()

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray_icon = QSystemTrayIcon(self)
        icon = self.windowIcon()
        if icon.isNull():
            return
        self.tray_icon.setIcon(icon)

        self.tray_menu = QMenu()
        self.tray_action_show = self.tray_menu.addAction("")
        self.tray_action_show.triggered.connect(self._show_from_tray)
        self.tray_action_scan = self.tray_menu.addAction("")
        self.tray_action_scan.triggered.connect(self._perform_scan)
        self.tray_menu.addSeparator()
        self.tray_action_quit = self.tray_menu.addAction("")
        self.tray_action_quit.triggered.connect(self._quit_app)

        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _show_from_tray(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_from_tray()

    def _quit_app(self):
        self._really_quit = True
        self.close()

    # ─── Lebenszyklus ─────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        if not self._grid_initialized:
            self._grid_initialized = True
            self._check_first_launch()

    def closeEvent(self, event):
        if (self.config.minimize_to_tray and self.tray_icon is not None
                and not self._really_quit):
            event.ignore()
            self.hide()
            return

        if self._scan_thread is not None and self._scan_thread.isRunning():
            self._scan_thread.wait(3000)
        self.launcher_manager.shutdown()
        self.config.window_size = self.size()
        self.config.window_pos = self.pos()
        self.config.save_settings()
        super().closeEvent(event)

    # ─── Scan (Background-Thread) ─────────────────────────────────────────

    def _check_first_launch(self):
        if self._force_rescan or self.scanner.should_perform_scan():
            self._perform_scan()
        else:
            self._load_games_from_db()

    def _perform_scan(self):
        if self._scan_thread is not None and self._scan_thread.isRunning():
            return
        self.refresh_button.setEnabled(False)
        self.status_label.setText(tr("status.scanning"))

        self._scan_thread = ScanThread(self.scanner, parent=self)
        self._scan_thread.scan_finished.connect(self._on_scan_finished)
        self._scan_thread.scan_error.connect(self._on_scan_error)
        self._scan_thread.start()

    def _on_scan_finished(self, result: ScanResult):
        self.refresh_button.setEnabled(True)
        self._load_games_from_db()
        self.status_label.setText(
            tr("status.scan_done",
               count=result.total_games,
               seconds=result.scan_duration_seconds)
        )

    def _on_scan_error(self, message: str):
        self.refresh_button.setEnabled(True)
        self.status_label.setText(tr("status.scan_error"))
        QMessageBox.critical(self, tr("dlg.scan_title"),
                             tr("dlg.scan_text", error=message))

    def _on_refresh_clicked(self):
        self._perform_scan()

    # ─── Anzeige, Filter, Favoriten-Sektion ───────────────────────────────

    def _load_games_from_db(self):
        try:
            self.all_games = self.db.get_all_games(include_hidden=False)
        except Exception as e:
            logging.error(f"Fehler beim Laden der Spiele-Bibliothek: {e}", exc_info=True)
            self.all_games = []
            QMessageBox.warning(self, tr("dlg.db_title"), tr("dlg.db_text", error=e))

        present = {game.launcher_type for game in self.all_games}
        if self._launcher_filter is not None and self._launcher_filter not in present:
            self._launcher_filter = None

        self.filter_bar.set_available_launchers(
            self.all_games, selected=self._launcher_filter
        )
        self._apply_filters()

    def _on_search_changed(self, text: str):
        self.search_timer.start()

    def _on_search_return_pressed(self):
        if self._current_games:
            self._on_game_clicked(self._current_games[0])

    def _on_launcher_filter_changed(self, launcher_type):
        self._launcher_filter = launcher_type
        self._apply_filters()

    def _apply_filters(self):
        games = self.all_games

        if self._launcher_filter is not None:
            games = [g for g in games if g.launcher_type == self._launcher_filter]

        search_term = self.search_input.text().strip().lower()
        if search_term:
            norm_term = normalize_name(search_term)
            games = [
                g for g in games
                if norm_term in normalize_name(g.name)
                or norm_term in normalize_name(g.launcher_display_name)
            ]

        games = sorted(games, key=lambda g: (not g.is_favorite, g.display_name.lower()))

        is_filtered = bool(search_term) or self._launcher_filter is not None
        self._display_games(games, is_filtered=is_filtered)

        if is_filtered:
            filter_name = (
                self._launcher_filter.name.replace("_", " ").title()
                if self._launcher_filter else tr("filter.all")
            )
            search_part = f", Suche: '{search_term}'" if search_term else ""
            self.status_label.setText(
                tr("status.filter", count=len(games),
                   filter=filter_name, search=search_part)
            )
        else:
            self.status_label.setText(tr("status.library", count=len(self.all_games)))

    def _display_games(self, games: list, is_filtered: bool):
        self._current_games = games
        self._clear_game_grid()

        if not games:
            self.games_layout.addWidget(EmptyPlaceholder(), 0, 0)
            self._current_columns = 0
            return

        columns = self._calc_columns()
        self._current_columns = columns

        favorites = [g for g in games if g.is_favorite]
        others = [g for g in games if not g.is_favorite]

        row = 0
        if favorites:
            row = self._add_section(row, columns, tr("section.favorites"), favorites)
        if others:
            if favorites:
                self._add_section(row, columns, tr("section.all"), others)
            else:
                self._add_cards(others, row, columns)

        if is_filtered:
            self.games_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        else:
            self.games_layout.setAlignment(Qt.Alignment())

    def _add_section(self, row: int, columns: int, title: str, games: list) -> int:
        header = QLabel(title)
        header.setObjectName("section_header")
        self.games_layout.addWidget(header, row, 0, 1, columns)
        return self._add_cards(games, row + 1, columns)

    def _add_cards(self, games: list, start_row: int, columns: int) -> int:
        for index, game in enumerate(games):
            card = GameCard(game, self.icon_loader, self.launcher_icons)
            card.clicked.connect(self._on_game_clicked)
            card.context_requested.connect(self._on_context_requested)
            self.games_layout.addWidget(card, start_row + index // columns,
                                          index % columns)
        return start_row + (len(games) + columns - 1) // columns

    def _calc_columns(self) -> int:
        available = self.scroll_area.viewport().width() - 60
        return max(2, available // (GameCard.CARD_WIDTH + 16))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._grid_initialized or not self._current_games:
            return
        new_width = self.scroll_area.viewport().width()
        if abs(new_width - self._last_grid_width) < (GameCard.CARD_WIDTH + 16):
            return
        self._resize_timer.start()

    def _rebuild_grid(self):
        self._last_grid_width = self.scroll_area.viewport().width()
        new_columns = self._calc_columns()
        if new_columns != self._current_columns:
            is_filtered = (bool(self.search_input.text().strip())
                           or self._launcher_filter is not None)
            self._display_games(self._current_games, is_filtered=is_filtered)

    def _clear_game_grid(self):
        while self.games_layout.count():
            child = self.games_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    # ─── Launcher-Events ──────────────────────────────────────────────────

    def _on_game_launched(self, game: Game):
        self.status_label.setText(tr("status.launching", name=game.name))

    def _on_session_finished(self, game: Game, minutes: int):
        try:
            self.all_games = self.db.get_all_games(include_hidden=False)
        except Exception as e:
            logging.error(f"Fehler beim Neuladen nach Session: {e}")
            return
        present = {g.launcher_type for g in self.all_games}
        if self._launcher_filter is not None and self._launcher_filter not in present:
            self._launcher_filter = None
        self.filter_bar.set_available_launchers(
            self.all_games, selected=self._launcher_filter
        )
        self._apply_filters()
        self.status_label.setText(
            tr("status.session_end", name=game.name, minutes=minutes)
        )

    # ─── Kontextmenü ──────────────────────────────────────────────────────

    def _on_context_requested(self, game: Game, global_pos: QPoint):
        menu = QMenu(self)
        action_start = menu.addAction(tr("menu.start"))
        menu.addSeparator()
        if game.is_favorite:
            action_favorite = menu.addAction(tr("menu.fav_remove"))
        else:
            action_favorite = menu.addAction(tr("menu.fav_add"))
        menu.addSeparator()
        action_folder = menu.addAction(tr("menu.folder"))
        action_launcher = menu.addAction(tr("menu.launcher"))
        menu.addSeparator()
        action_hide = menu.addAction(tr("menu.hide"))

        chosen = menu.exec(global_pos)

        if chosen == action_start:
            self._on_game_clicked(game)
        elif chosen == action_favorite:
            self._toggle_favorite(game)
        elif chosen == action_folder:
            self._open_install_folder(game)
        elif chosen == action_launcher:
            self._show_launcher_info(game)
        elif chosen == action_hide:
            self._hide_game(game)

    def _toggle_favorite(self, game: Game):
        new_state = not game.is_favorite
        if self.db.set_game_favorite(game, new_state):
            game.is_favorite = new_state
            self._load_games_from_db()
            key = "status.fav_on" if new_state else "status.fav_off"
            self.status_label.setText(tr(key, name=game.name))
        else:
            QMessageBox.warning(self, tr("dlg.error"),
                                tr("dlg.error_fav", name=game.name))

    def _open_install_folder(self, game: Game):
        target = game.executable_path
        try:
            if target and target.exists():
                subprocess.Popen(["explorer", f'/select,"{target}"'])
            elif game.install_path and game.install_path.exists():
                os.startfile(str(game.install_path))
            else:
                QMessageBox.warning(self, tr("dlg.folder_missing"),
                                    tr("dlg.folder_missing_text"))
        except Exception as e:
            logging.error(f"Fehler beim Öffnen des Ordners: {e}")
            QMessageBox.warning(self, tr("dlg.error"),
                                tr("dlg.error_folder", error=e))

    def _show_launcher_info(self, game: Game):
        running = self.launcher_manager.is_launcher_running(game.launcher_type)
        status = tr("info.status_running") if running else tr("info.status_stopped")
        favorite = tr("info.favorite_yes") if game.is_favorite else tr("info.favorite_no")

        info_text = (
            f"{tr('info.game')}:          {game.display_name}\n"
            f"{tr('info.launcher')}:       {game.launcher_display_name}\n"
            f"{tr('info.status')}:         {status}\n"
            f"{tr('info.favorite')}:        {favorite}\n\n"
            f"{tr('info.playtime')}:      {game.playtime_display or '–'}\n"
            f"{game.last_played_display or '–'}\n\n"
            f"{tr('info.path')}:\n{game.install_path or tr('info.unknown')}\n\n"
            f"{tr('info.command')}:\n{self.launcher_manager.get_launch_command(game)}"
        )
        QMessageBox.information(self, tr("info.title"), info_text)

    def _hide_game(self, game: Game):
        if self.db.set_game_hidden(game, True):
            self.status_label.setText(tr("status.hidden", name=game.name))
            self._load_games_from_db()
        else:
            QMessageBox.warning(self, tr("dlg.error"),
                                tr("dlg.error_hide", name=game.name))

    # ─── Spiele-Start ─────────────────────────────────────────────────────

    def _on_game_clicked(self, game: Game):
        command = self.launcher_manager.get_launch_command(game)

        if "://" not in command and not game.executable_path.exists():
            QMessageBox.warning(
                self, tr("dlg.missing_title"),
                tr("dlg.missing_text", path=game.executable_path)
            )
            return

        if self.launcher_manager.launch_game(game):
            self.status_label.setText(tr("status.launching", name=game.name))
        else:
            QMessageBox.critical(self, tr("dlg.start_title"),
                                 tr("dlg.start_text", name=game.name))