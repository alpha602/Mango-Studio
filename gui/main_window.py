import os
import logging
import subprocess
import psutil
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QGridLayout, QFrame,
    QMessageBox, QApplication, QMenu, QLabel, QComboBox, QPushButton
)
from PySide6.QtCore import Qt, QTimer, QPoint, QThread, Signal
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
    SearchBar, AccentButton, EmptyPlaceholder, 
    LauncherFilterBar, SidebarNavigation
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STYLES_PATH = PROJECT_ROOT / "assets" / "styles" / "main.qss"
WINDOW_ICON_CANDIDATES = [
    PROJECT_ROOT / "assets" / "icons" / "mango.ico",
    PROJECT_ROOT / "assets" / "icons" / "mango.png",
]

class SystemMonitorThread(QThread):
    stats_updated = Signal(str)
    def run(self):
        while True:
            try:
                self.stats_updated.emit(f"CPU {psutil.cpu_percent(interval=1.0):.0f}%  •  RAM {psutil.virtual_memory().percent:.0f}%")
            except Exception:
                self.stats_updated.emit("CPU --%  •  RAM ---%")

class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, force_rescan: bool = False):
        super().__init__()
        self.config = config
        self._force_rescan = force_rescan
        set_language(config.language)
        self.resize(self.config.window_size)
        self.move(self.config.window_pos)

        self.db = Database(self.config)
        self.scanner = Scanner(self.config, self.db)
        self.icon_loader = IconLoader(self.config)
        self.launcher_icons = LauncherIconProvider(self.config, self.db)
        self.launcher_manager = LauncherManager(self.db, parent=self)
        self.launcher_manager.game_launched.connect(self._on_game_launched)
        self.launcher_manager.session_finished.connect(self._on_session_finished)

        self.all_games: list = []
        self._current_games: list = []
        self._current_columns = 0
        self._last_grid_width = 0
        self._grid_initialized = False
        self._launcher_filter: LauncherType = None
        self._sort_mode: str = "name_asc"
        self._current_view: str = "library" # NEU: View State
        self._scan_thread: ScanThread = None

        self.search_timer = QTimer(singleShot=True, interval=250, timeout=self._apply_filters)
        self._resize_timer = QTimer(singleShot=True, interval=150, timeout=self._rebuild_grid)

        self._apply_stylesheet()
        self._apply_window_icon()
        self._init_ui()
        
        self.sys_monitor = SystemMonitorThread()
        self.sys_monitor.stats_updated.connect(self.system_monitor.setText)
        self.sys_monitor.start()

    def _apply_stylesheet(self):
        if STYLES_PATH.exists(): QApplication.instance().setStyleSheet(STYLES_PATH.read_text(encoding="utf-8"))

    def _apply_window_icon(self):
        for c in WINDOW_ICON_CANDIDATES:
            if c.exists(): self.setWindowIcon(QIcon(str(c))); return

    def _init_ui(self):
        cw = QWidget(); self.setCentralWidget(cw)
        rl = QHBoxLayout(cw); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)

        self.sidebar = SidebarNavigation()
        self.sidebar.view_changed.connect(self._on_sidebar_changed)
        rl.addWidget(self.sidebar)

        rp = QWidget(); rp.setObjectName("right_panel")
        rpl = QVBoxLayout(rp); rpl.setContentsMargins(0,0,0,0); rpl.setSpacing(0)
        self._create_header(rpl); self._create_content_area(rpl); self._create_footer(rpl)
        rl.addWidget(rp, 1)
        self.retranslate_ui()

    def _create_header(self, layout: QVBoxLayout):
        hw = QWidget(); hw.setObjectName("header_widget")
        hl = QHBoxLayout(hw); hl.setContentsMargins(40, 30, 40, 20); hl.setSpacing(24)
        tb = QVBoxLayout(); tb.setSpacing(4)
        self.title_label = QLabel("Mango Studio"); self.title_label.setObjectName("app_title")
        self.subtitle_label = QLabel("Your game hub"); self.subtitle_label.setObjectName("app_subtitle")
        tb.addWidget(self.title_label); tb.addWidget(self.subtitle_label)
        self.search_input = SearchBar(); self.search_input.textChanged.connect(self._on_search_changed); self.search_input.returnPressed.connect(self._on_search_return_pressed)
        self.scan_button = AccentButton("Scan for games"); self.scan_button.clicked.connect(self._perform_scan)
        hl.addLayout(tb); hl.addWidget(self.search_input, 1); hl.addWidget(self.scan_button)
        layout.addWidget(hw)

    def _create_content_area(self, layout: QVBoxLayout):
        cw = QWidget(); cw.setObjectName("content_widget")
        cl = QVBoxLayout(cw); cl.setContentsMargins(40, 10, 40, 20); cl.setSpacing(20)
        sh = QHBoxLayout(); sh.setSpacing(15)
        self.status_label = QLabel("Loading..."); self.status_label.setObjectName("status_label")
        self.filter_bar = LauncherFilterBar(); self.filter_bar.filter_changed.connect(self._on_launcher_filter_changed)
        sh.addWidget(self.status_label); sh.addStretch(); sh.addWidget(self.filter_bar)
        self.sort_combo = QComboBox(); self.sort_combo.addItems(["Sort: Name A-Z", "Sort: Name Z-A", "Sort: Size"]); self.sort_combo.setObjectName("sort_combo"); self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        sh.addWidget(self.sort_combo)
        self.view_toggle = QPushButton("▦"); self.view_toggle.setObjectName("view_toggle"); self.view_toggle.setFixedSize(36, 36)
        sh.addWidget(self.view_toggle)
        cl.addLayout(sh)
        self.scroll_area = QScrollArea(); self.scroll_area.setObjectName("game_scroll"); self.scroll_area.setWidgetResizable(True); self.scroll_area.setFrameShape(QFrame.NoFrame); self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.games_container = QWidget(); self.games_container.setObjectName("games_container")
        self.games_layout = QGridLayout(self.games_container); self.games_layout.setSpacing(24); self.games_layout.setContentsMargins(0, 10, 10, 0)
        self.scroll_area.setWidget(self.games_container); cl.addWidget(self.scroll_area, 1)
        layout.addWidget(cw, 1)

    def _create_footer(self, layout: QVBoxLayout):
        fw = QWidget(); fw.setObjectName("footer_widget")
        fl = QHBoxLayout(fw); fl.setContentsMargins(40, 15, 40, 15)
        self.version_label = QLabel(f"Mango Studio v{self.config.APP_VERSION}"); self.version_label.setObjectName("footer_version")
        self.footer_status = QLabel("Ready"); self.footer_status.setObjectName("footer_status"); self.footer_status.setAlignment(Qt.AlignCenter)
        self.system_monitor = QLabel("CPU --%  •  RAM ---%"); self.system_monitor.setObjectName("system_monitor"); self.system_monitor.setAlignment(Qt.AlignRight)
        fl.addWidget(self.version_label); fl.addWidget(self.footer_status, 1); fl.addWidget(self.system_monitor)
        layout.addWidget(fw)

    def retranslate_ui(self):
        self.setWindowTitle(f"{tr('app.title')} - {tr('app.subtitle')}")
        self.title_label.setText(tr('app.title')); self.subtitle_label.setText(tr('app.subtitle'))
        self.scan_button.setText("Scan for games"); self.search_input.retranslate(); self._apply_filters()

    # ─── Punkt 5: Echte View-Logik ────────────────────────────────────────
    def _on_sidebar_changed(self, view_key: str):
        self._current_view = view_key
        if view_key == "settings":
            self._open_settings(tab_index=0)
        elif view_key == "folders":
            self._open_settings(tab_index=1) # Punkt 5.4: Direkt zum Ordner-Tab springen
        else:
            self._apply_filters()

    def _open_settings(self, tab_index: int = 0):
        dialog = SettingsDialog(self.config, self.db, parent=self)
        dialog.set_active_tab(tab_index) # Wir rufen eine neue Methode im Dialog auf
        dialog.settings_changed.connect(self._on_settings_changed)
        dialog.rescan_requested.connect(self._perform_scan)
        dialog.exec()

    def _on_settings_changed(self):
        self.retranslate_ui(); self._load_games_from_db()

    def _on_sort_changed(self, index: int):
        self._sort_mode = ["name_asc", "name_desc", "size_desc"][index]
        self._apply_filters()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._grid_initialized: self._grid_initialized = True; self._check_first_launch()

    def closeEvent(self, event):
        self.sys_monitor.terminate()
        if self._scan_thread and self._scan_thread.isRunning(): self._scan_thread.wait(3000)
        self.launcher_manager.shutdown()
        self.config.window_size, self.config.window_pos = self.size(), self.pos()
        self.config.save_settings(); super().closeEvent(event)

    def _check_first_launch(self):
        if self._force_rescan or self.scanner.should_perform_scan(): self._perform_scan()
        else: self._load_games_from_db()

    def _perform_scan(self):
        if self._scan_thread and self._scan_thread.isRunning(): return
        self.scan_button.setEnabled(False); self.scan_button.setText("Scanning..."); self.footer_status.setText("Calculating folder sizes and scanning...")
        self._scan_thread = ScanThread(self.scanner, parent=self)
        self._scan_thread.scan_finished.connect(self._on_scan_finished); self._scan_thread.scan_error.connect(self._on_scan_error)
        self._scan_thread.start()

    def _on_scan_finished(self, result: ScanResult):
        self.scan_button.setEnabled(True); self.scan_button.setText("Scan for games")
        self._load_games_from_db(); self.footer_status.setText(f"Scanning complete: All {result.total_games} games indexed")

    def _on_scan_error(self, msg: str):
        self.scan_button.setEnabled(True); self.scan_button.setText("Scan for games")
        self.footer_status.setText("Scan failed."); QMessageBox.critical(self, tr("dlg.scan_title"), tr("dlg.scan_text", error=msg))

    def _load_games_from_db(self):
        try: self.all_games = self.db.get_all_games(include_hidden=False)
        except Exception as e:
            self.all_games = []; QMessageBox.warning(self, tr("dlg.db_title"), tr("dlg.db_text", error=e))
        present = {g.launcher_type for g in self.all_games}
        if self._launcher_filter and self._launcher_filter not in present: self._launcher_filter = None
        self.filter_bar.set_available_launchers(self.all_games, selected=self._launcher_filter)
        self._apply_filters()

    def _on_search_changed(self, text: str): self.search_timer.start()
    def _on_search_return_pressed(self):
        if self._current_games: self._on_game_clicked(self._current_games[0])
    def _on_launcher_filter_changed(self, lt): self._launcher_filter = lt; self._apply_filters()

    def _apply_filters(self):
        games = self.all_games

        # Punkt 5.1 - 5.3: View-basiertes Filtern
        if self._current_view == "favorites":
            games = [g for g in games if g.is_favorite]
        elif self._current_view == "recent":
            games = sorted(games, key=lambda g: g.date_added, reverse=True)[:20]

        if self._launcher_filter: games = [g for g in games if g.launcher_type == self._launcher_filter]

        st = self.search_input.text().strip().lower()
        if st:
            nt = normalize_name(st)
            games = [g for g in games if nt in normalize_name(g.name) or nt in normalize_name(g.launcher_display_name)]

        if self._sort_mode == "name_asc": games = sorted(games, key=lambda g: g.display_name.lower())
        elif self._sort_mode == "name_desc": games = sorted(games, key=lambda g: g.display_name.lower(), reverse=True)
        elif self._sort_mode == "size_desc": games = sorted(games, key=lambda g: g.size_bytes, reverse=True)

        is_filtered = bool(st) or self._launcher_filter is not None or self._current_view != "library"
        self._display_games(games, is_filtered=is_filtered)

        if is_filtered:
            fn = self._launcher_filter.name.replace("_", " ").title() if self._launcher_filter else tr("filter.all")
            sp = f", search: '{st}'" if st else ""
            self.status_label.setText(f"{len(games)} games (view: {self._current_view}, filter: {fn}{sp})")
        else:
            self.status_label.setText(f"Library  •  {len(self.all_games)} games detected")

    def _display_games(self, games: list, is_filtered: bool):
        self._current_games = games; self._clear_game_grid()
        if not games: self.games_layout.addWidget(EmptyPlaceholder(), 0, 0); self._current_columns = 0; return
        
        cols = self._calc_columns(); self._current_columns = cols
        
        # Punkt 5.1: In der Library-Ansicht keine extra Favoriten-Sektion mehr, alles gemischt
        for idx, g in enumerate(games):
            card = GameCard(g, self.icon_loader, self.launcher_icons)
            card.clicked.connect(self._on_game_clicked); card.context_requested.connect(self._on_context_requested)
            self.games_layout.addWidget(card, idx // cols, idx % cols)
            
        self.games_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop if is_filtered else Qt.Alignment())

    def _calc_columns(self) -> int: return max(2, (self.scroll_area.viewport().width() - 20) // (GameCard.CARD_WIDTH + 24))
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._grid_initialized or not self._current_games: return
        if abs(self.scroll_area.viewport().width() - self._last_grid_width) < (GameCard.CARD_WIDTH + 24): return
        self._resize_timer.start()
    def _rebuild_grid(self):
        self._last_grid_width = self.scroll_area.viewport().width()
        if self._calc_columns() != self._current_columns: self._display_games(self._current_games, bool(self.search_input.text().strip()) or self._launcher_filter or self._current_view != "library")
    def _clear_game_grid(self):
        while self.games_layout.count():
            c = self.games_layout.takeAt(0)
            if c.widget(): c.widget().deleteLater()

    def _on_game_launched(self, g: Game): self.footer_status.setText(f"Launching {g.name}...")
    def _on_session_finished(self, g: Game, m: int):
        try: self.all_games = self.db.get_all_games(include_hidden=False)
        except: return
        self._apply_filters(); self.footer_status.setText(f"{g.name}: Session ended (+{m} min)")

    def _on_context_requested(self, g: Game, pos: QPoint):
        m = QMenu(self)
        a_s = m.addAction(tr("menu.start")); m.addSeparator()
        a_f = m.addAction(tr("menu.fav_remove") if g.is_favorite else tr("menu.fav_add")); m.addSeparator()
        a_d = m.addAction(tr("menu.folder")); a_l = m.addAction(tr("menu.launcher")); m.addSeparator()
        a_h = m.addAction(tr("menu.hide"))
        c = m.exec(pos)
        if c == a_s: self._on_game_clicked(g)
        elif c == a_f: self._toggle_favorite(g)
        elif c == a_d: self._open_install_folder(g)
        elif c == a_l: self._show_launcher_info(g)
        elif c == a_h: self._hide_game(g)

    def _toggle_favorite(self, g: Game):
        if self.db.set_game_favorite(g, not g.is_favorite): g.is_favorite = not g.is_favorite; self._load_games_from_db()
    def _open_install_folder(self, g: Game):
        try:
            if g.executable_path.exists(): subprocess.Popen(["explorer", f'/select,"{g.executable_path}"'])
            elif g.install_path.exists(): os.startfile(str(g.install_path))
        except Exception as e: QMessageBox.warning(self, "Error", str(e))
    def _show_launcher_info(self, g: Game):
        r = self.launcher_manager.is_launcher_running(g.launcher_type)
        QMessageBox.information(self, "Info", f"Game: {g.display_name}\nLauncher: {g.launcher_display_name} ({'Running' if r else 'Stopped'})\nSize: {g.size_display or '-'}\nPath: {g.install_path}")
    def _hide_game(self, g: Game):
        if self.db.set_game_hidden(g, True): self._load_games_from_db()
    def _on_game_clicked(self, g: Game):
        cmd = self.launcher_manager.get_launch_command(g)
        if "://" not in cmd and not g.executable_path.exists(): QMessageBox.warning(self, "Not found", f"Exe missing: {g.executable_path}"); return
        if self.launcher_manager.launch_game(g): self.footer_status.setText(f"Launching {g.name}...")