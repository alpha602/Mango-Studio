from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLineEdit, QPushButton, QLabel, QWidget, QHBoxLayout, QButtonGroup
)

from core.i18n import tr
from data.models import LauncherType


class SearchBar(QLineEdit):
    """Wiederverwendbare, gestylte Suchleiste (übersetzbar)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("search_bar")
        self.setFixedHeight(50)
        self.setClearButtonEnabled(True)
        self.retranslate()

    def retranslate(self):
        self.setPlaceholderText(tr("search.placeholder"))


class PrimaryButton(QPushButton):
    """Standard-Button für Hauptaktionen."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("primary_button")
        self.setFixedHeight(40)
        self.setCursor(Qt.PointingHandCursor)


class EmptyPlaceholder(QLabel):
    """Platzhalter-Label für leere Ansichten."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text or tr("empty.games"), parent)
        self.setObjectName("empty_placeholder")
        self.setAlignment(Qt.AlignCenter)


class LauncherFilterBar(QWidget):
    """
    Chip-Leiste zum Filtern der Bibliothek nach Launcher.
    Emittiert LauncherType oder None (= 'Alle').
    """
    filter_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("filter_bar")

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._button_group.buttonClicked.connect(self._on_button_clicked)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(30, 6, 30, 6)
        self._layout.setSpacing(8)

        self._launcher_buttons: dict = {}
        self.set_available_launchers([])

    def set_available_launchers(self, games: list, selected=None):
        """Baut die Chips neu auf; 'selected' bleibt aktiv erhalten."""
        for button in list(self._button_group.buttons()):
            self._button_group.removeButton(button)
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._launcher_buttons = {}

        present = []
        for game in games:
            if game.launcher_type not in present:
                present.append(game.launcher_type)
        present.sort(key=lambda lt: lt.name)

        self._layout.addStretch()

        all_button = self._make_chip(f"{tr('filter.all')} ({len(games)})", None)
        self._layout.addWidget(all_button)
        self._launcher_buttons[None] = all_button

        for launcher_type in present:
            count = sum(1 for g in games if g.launcher_type == launcher_type)
            label = f"{launcher_type.name.replace('_', ' ').title()} ({count})"
            button = self._make_chip(label, launcher_type)
            self._layout.addWidget(button)
            self._launcher_buttons[launcher_type] = button

        self._layout.addStretch()

        target = self._launcher_buttons.get(selected)
        if target is None:
            target = self._launcher_buttons.get(None)
        target.setChecked(True)

    def _make_chip(self, label: str, launcher_type) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("filter_chip")
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setProperty("launcher_type", launcher_type)
        self._button_group.addButton(button)
        return button

    def _on_button_clicked(self, button):
        self.filter_changed.emit(button.property("launcher_type"))