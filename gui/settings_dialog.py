import logging
import sys
import winreg
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QComboBox, QCheckBox, QListWidget, QListWidgetItem,
    QPushButton, QFileDialog, QDialogButtonBox, QLabel,
)

from core.config import AppConfig
from core.i18n import tr, set_language
from data.database import Database
from data.models import Game

AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "MangoStudio"

def _autostart_command() -> str:
    if getattr(sys, "frozen", False): return f'"{sys.executable}"'
    return f'"{sys.executable}" "{Path(__file__).resolve().parents[1] / "main.py"}"'

def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as k: winreg.QueryValueEx(k, AUTOSTART_NAME); return True
    except OSError: return False

def set_autostart(enabled: bool) -> bool:
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as k:
            if enabled: winreg.SetValueEx(k, AUTOSTART_NAME, 0, winreg.REG_SZ, _autostart_command())
            else:
                try: winreg.DeleteValue(k, AUTOSTART_NAME)
                except FileNotFoundError: pass
        return True
    except OSError as e: logging.error(f"Autostart error: {e}"); return False

class SettingsDialog(QDialog):
    settings_changed = Signal()
    rescan_requested = Signal()

    def __init__(self, config: AppConfig, database: Database, parent=None):
        super().__init__(parent)
        self.config, self.db = config, database
        self._folders_changed = False
        self.setWindowTitle(tr("settings.title"))
        self.setMinimumSize(700, 550) # Punkt 6: Größerer Dialog

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_general_tab(), tr("settings.tab_general"))
        self.tabs.addTab(self._build_folders_tab(), tr("settings.tab_folders"))
        self.tabs.addTab(self._build_hidden_tab(), tr("settings.tab_hidden"))
        layout.addWidget(self.tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def set_active_tab(self, index: int):
        """Punkt 5.4: Erlaubt das direkte Springen zu einem Tab."""
        self.tabs.setCurrentIndex(index)

    def _build_general_tab(self) -> QWidget:
        p = QWidget(); l = QVBoxLayout(p); l.setSpacing(15)
        lr = QHBoxLayout(); lr.addWidget(QLabel(tr("settings.language")))
        self.lang_combo = QComboBox(); self.lang_combo.addItems(["Deutsch", "English"]); self.lang_combo.setCurrentIndex(0 if self.config.language == "de" else 1)
        lr.addWidget(self.lang_combo); lr.addStretch(); l.addLayout(lr)
        self.tray_chk = QCheckBox(tr("settings.tray")); self.tray_chk.setChecked(self.config.minimize_to_tray); l.addWidget(self.tray_chk)
        self.auto_chk = QCheckBox(tr("settings.autostart")); self.auto_chk.setChecked(is_autostart_enabled()); l.addWidget(self.auto_chk)
        l.addStretch(); return p

    def _build_folders_tab(self) -> QWidget:
        p = QWidget(); l = QVBoxLayout(p)
        h = QLabel(tr("settings.folders.hint")); h.setWordWrap(True); l.addWidget(h)
        self.folder_list = QListWidget(); l.addWidget(self.folder_list)
        for f in self.config.custom_scan_folders: self.folder_list.addItem(f)
        br = QHBoxLayout()
        ab = QPushButton(tr("settings.folders.add")); ab.clicked.connect(self._add_folder)
        rb = QPushButton(tr("settings.folders.remove")); rb.clicked.connect(self._remove_folder)
        br.addWidget(ab); br.addWidget(rb); br.addStretch(); l.addLayout(br); return p

    def _build_hidden_tab(self) -> QWidget:
        p = QWidget(); l = QVBoxLayout(p)
        self.hidden_list = QListWidget(); l.addWidget(self.hidden_list); self._refresh_hidden()
        sb = QPushButton(tr("settings.hidden.show")); sb.clicked.connect(self._unhide); l.addWidget(sb); return p

    def _add_folder(self):
        f = QFileDialog.getExistingDirectory(self, tr("settings.folders.add"))
        if f and f not in self.config.custom_scan_folders:
            self.config.custom_scan_folders.append(f); self.folder_list.addItem(f); self._folders_changed = True

    def _remove_folder(self):
        r = self.folder_list.currentRow()
        if r >= 0:
            f = self.folder_list.item(r).text()
            if f in self.config.custom_scan_folders: self.config.custom_scan_folders.remove(f)
            self.folder_list.takeItem(r); self._folders_changed = True

    def _refresh_hidden(self):
        self.hidden_list.clear()
        hg = [g for g in self.db.get_all_games(include_hidden=True) if g.is_hidden]
        for g in hg:
            i = QListWidgetItem(f"{g.display_name}  ({g.launcher_display_name})"); i.setData(Qt.UserRole, g); self.hidden_list.addItem(i)
        if not hg: self.hidden_list.addItem(tr("settings.hidden.empty"))

    def _unhide(self):
        i = self.hidden_list.currentItem()
        if i and isinstance(i.data(Qt.UserRole), Game) and self.db.set_game_hidden(i.data(Qt.UserRole), False):
            self._refresh_hidden(); self.settings_changed.emit()

    def accept(self):
        self.config.language = "de" if self.lang_combo.currentIndex() == 0 else "en"
        set_language(self.config.language); self.config.minimize_to_tray = self.tray_chk.isChecked(); self.config.save_settings()
        if self.auto_chk.isChecked() != is_autostart_enabled(): set_autostart(self.auto_chk.isChecked())
        self.settings_changed.emit()
        if self._folders_changed: self.rescan_requested.emit()
        super().accept()