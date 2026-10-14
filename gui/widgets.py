from pathlib import Path
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QLineEdit, QPushButton, QLabel, QWidget, QHBoxLayout, QButtonGroup,
    QListWidget, QListWidgetItem, QAbstractItemView
)
from PySide6.QtGui import QIcon

from core.i18n import tr
from data.models import LauncherType

ASSETS_ICONS_DIR = Path(__file__).resolve().parents[1] / "assets" / "icons"

class SearchBar(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent); self.setObjectName("search_bar"); self.setFixedHeight(48); self.setClearButtonEnabled(True); self.retranslate()
    def retranslate(self): self.setPlaceholderText(tr("search.placeholder"))

class AccentButton(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent); self.setObjectName("accent_button"); self.setFixedHeight(40); self.setCursor(Qt.PointingHandCursor)

class EmptyPlaceholder(QLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text or tr("empty.games"), parent); self.setObjectName("empty_placeholder"); self.setAlignment(Qt.AlignCenter)

class SidebarNavigation(QListWidget):
    view_changed = Signal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar_nav"); self.setFrameShape(QListWidget.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SingleSelection); self.setSpacing(8) # Punkt 4: Mehr Spacing
        self.setIconSize(QSize(28, 28)) # Punkt 4: Größere Icons

        items = [("library", "Library", "library.png"), ("favorites", "Favorites", "favorite.png"), ("recent", "Recently Added", "recently.png"), ("folders", "Scan Folders", "folder_scan.png"), ("settings", "Settings", "settings.png")]
        for k, lbl, ic in items:
            it = QListWidgetItem(f"   {lbl}") # Extra Padding im Text
            ip = ASSETS_ICONS_DIR / ic
            if ip.exists(): it.setIcon(QIcon(str(ip)))
            else: it.setText(f"{ {'library':'📚','favorites':'⭐','recent':'🕒','folders':'📁','settings':'⚙'}.get(k,'') }   {lbl}")
            it.setData(Qt.UserRole, k); self.addItem(it)
        self.setCurrentRow(0); self.currentItemChanged.connect(lambda c, p: c and self.view_changed.emit(c.data(Qt.UserRole)))

class LauncherFilterBar(QWidget):
    filter_changed = Signal(object)
    def __init__(self, parent=None):
        super().__init__(parent); self.setObjectName("filter_bar")
        self._bg = QButtonGroup(self); self._bg.setExclusive(True); self._bg.buttonClicked.connect(lambda b: self.filter_changed.emit(b.property("launcher_type")))
        self._l = QHBoxLayout(self); self._l.setContentsMargins(0,0,0,0); self._l.setSpacing(8); self._btns = {}; self.set_available_launchers([])

    def set_available_launchers(self, games: list, selected=None):
        for b in list(self._bg.buttons()): self._bg.removeButton(b)
        while self._l.count():
            i = self._l.takeAt(0)
            if i.widget(): i.widget().deleteLater()
        self._btns = {}
        pres = sorted(list({g.launcher_type for g in games}), key=lambda x: x.name)
        ab = self._mk(f"{tr('filter.all')} ({len(games)})", None); self._l.addWidget(ab); self._btns[None] = ab
        for lt in pres:
            b = self._mk(f"{lt.name.replace('_',' ').title()} ({sum(1 for g in games if g.launcher_type==lt)})", lt); self._l.addWidget(b); self._btns[lt] = b
        self._l.addStretch(); (self._btns.get(selected) or self._btns.get(None)).setChecked(True)

    def _mk(self, lbl, lt) -> QPushButton:
        b = QPushButton(lbl); b.setObjectName("filter_chip"); b.setCheckable(True); b.setCursor(Qt.PointingHandCursor); b.setProperty("launcher_type", lt); self._bg.addButton(b); return b