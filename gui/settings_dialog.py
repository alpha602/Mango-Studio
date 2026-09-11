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
    """Befehl für den Autostart-Registry-Eintrag (exe oder Script)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    main_py = Path(__file__).resolve().parents[1] / "main.py"
    return f'"{sys.executable}" "{main_py}"'


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as key:
            winreg.QueryValueEx(key, AUTOSTART_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    """Setzt oder entfernt den Autostart-Eintrag in der Windows-Registry."""
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ,
                                  _autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, AUTOSTART_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError as e:
        logging.error(f"Autostart konnte nicht geändert werden: {e}")
        return False


class SettingsDialog(QDialog):
    """
    Einstellungen: Sprache, Tray, Autostart, benutzerdefinierte Scan-Ordner
    und Verwaltung verborgener Spiele.
    """
    settings_changed = Signal()   # UI-Texte/Listen neu laden
    rescan_requested = Signal()   # Scan-Ordner geändert → Scan anstoßen

    def __init__(self, config: AppConfig, database: Database, parent=None):
        super().__init__(parent)
        self.config = config
        self.db = database
        self._folders_changed = False

        self.setWindowTitle(tr("settings.title"))
        self.setMinimumSize(560, 440)

        layout = QVBoxLayout(self)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_general_tab(), tr("settings.tab_general"))
        tabs.addTab(self._build_folders_tab(), tr("settings.tab_folders"))
        tabs.addTab(self._build_hidden_tab(), tr("settings.tab_hidden"))
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    # ─── Tabs ─────────────────────────────────────────────────────────────

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel(tr("settings.language")))
        self.language_combo = QComboBox()
        self.language_combo.addItems(["Deutsch", "English"])
        self.language_combo.setCurrentIndex(0 if self.config.language == "de" else 1)
        lang_row.addWidget(self.language_combo)
        lang_row.addStretch()
        layout.addLayout(lang_row)

        self.tray_check = QCheckBox(tr("settings.tray"))
        self.tray_check.setChecked(self.config.minimize_to_tray)
        layout.addWidget(self.tray_check)

        self.autostart_check = QCheckBox(tr("settings.autostart"))
        self.autostart_check.setChecked(is_autostart_enabled())
        layout.addWidget(self.autostart_check)

        layout.addStretch()
        return page

    def _build_folders_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        hint = QLabel(tr("settings.folders.hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.folder_list = QListWidget()
        for folder in self.config.custom_scan_folders:
            self.folder_list.addItem(folder)
        layout.addWidget(self.folder_list)

        button_row = QHBoxLayout()
        add_button = QPushButton(tr("settings.folders.add"))
        add_button.clicked.connect(self._add_folder)
        remove_button = QPushButton(tr("settings.folders.remove"))
        remove_button.clicked.connect(self._remove_folder)
        button_row.addWidget(add_button)
        button_row.addWidget(remove_button)
        button_row.addStretch()
        layout.addLayout(button_row)
        return page

    def _build_hidden_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.hidden_list = QListWidget()
        layout.addWidget(self.hidden_list)
        self._refresh_hidden_list()

        show_button = QPushButton(tr("settings.hidden.show"))
        show_button.clicked.connect(self._unhide_selected)
        layout.addWidget(show_button)
        return page

    # ─── Logik ────────────────────────────────────────────────────────────

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("settings.folders.add"))
        if not folder:
            return
        if folder in self.config.custom_scan_folders:
            return
        self.config.custom_scan_folders.append(folder)
        self.folder_list.addItem(folder)
        self._folders_changed = True

    def _remove_folder(self):
        row = self.folder_list.currentRow()
        if row < 0:
            return
        folder = self.folder_list.item(row).text()
        if folder in self.config.custom_scan_folders:
            self.config.custom_scan_folders.remove(folder)
        self.folder_list.takeItem(row)
        self._folders_changed = True

    def _refresh_hidden_list(self):
        self.hidden_list.clear()
        hidden_games = [g for g in self.db.get_all_games(include_hidden=True)
                        if g.is_hidden]
        for game in hidden_games:
            item = QListWidgetItem(f"{game.display_name}  ({game.launcher_display_name})")
            item.setData(Qt.UserRole, game)
            self.hidden_list.addItem(item)
        if not hidden_games:
            self.hidden_list.addItem(tr("settings.hidden.empty"))

    def _unhide_selected(self):
        item = self.hidden_list.currentItem()
        if item is None:
            return
        game = item.data(Qt.UserRole)
        if not isinstance(game, Game):
            return
        if self.db.set_game_hidden(game, False):
            self._refresh_hidden_list()
            self.settings_changed.emit()

    def accept(self):
        """Speichert alle Einstellungen und wendet sie an."""
        self.config.language = "de" if self.language_combo.currentIndex() == 0 else "en"
        set_language(self.config.language)
        self.config.minimize_to_tray = self.tray_check.isChecked()
        self.config.save_settings()

        if self.autostart_check.isChecked() != is_autostart_enabled():
            set_autostart(self.autostart_check.isChecked())

        self.settings_changed.emit()
        if self._folders_changed:
            self.rescan_requested.emit()
        super().accept()