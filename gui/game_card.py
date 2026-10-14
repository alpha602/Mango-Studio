import logging

from PySide6.QtCore import (
    QObject, QPoint, QPointF, Qt, Signal, QRunnable, QThreadPool, QPropertyAnimation
)
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import (
    QFrame, QLabel, QVBoxLayout, QGraphicsDropShadowEffect
)

from core.icon_loader import IconLoader
from core.launcher_icons import LauncherIconProvider
from core.i18n import tr
from data.models import Game


class _CoverSignals(QObject):
    """Signal-Brücke für den Cover-Worker."""
    finished = Signal(object, object)  # (Game, QImage)


class _CoverWorker(QRunnable):
    """Lädt ein Cover im Hintergrund-Thread (nur QImage, kein QPixmap)."""

    def __init__(self, icon_loader: IconLoader, game: Game):
        super().__init__()
        self._loader = icon_loader
        self._game = game
        self.signals = _CoverSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            image = self._loader.load_cover_image(self._game)
            self.signals.finished.emit(self._game, image)
        except Exception as e:
            logging.debug(f"Cover-Worker fehlgeschlagen für '{self._game.name}': {e}")


class GameCard(QFrame):
    """
    Spiele-Kachel (Phase 2.0 Design):
    Cover, sauberes Launcher-Icon-Overlay, Favoriten-Stern, Name, 
    Launcher-Name + Größe, Hover-Animation.
    """
    clicked = Signal(Game)
    context_requested = Signal(Game, QPoint)

    CARD_WIDTH = 180
    CARD_HEIGHT = 260

    def __init__(self, game: Game, icon_loader: IconLoader,
                 launcher_icons: LauncherIconProvider, parent=None):
        super().__init__(parent)
        self.game = game
        self.icon_loader = icon_loader
        self._worker = None

        self.setObjectName("game_card")
        self.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(self._build_tooltip())

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._emit_context)

        self._setup_shadow_effect()
        self._setup_ui(launcher_icons)
        self._start_cover_loading()

    def _build_tooltip(self) -> str:
        lines = [self.game.display_name,
                 tr("tooltip.launcher", launcher=self.game.launcher_display_name)]
        if self.game.size_display:
            lines.append(f"Size: {self.game.size_display}")
        if self.game.playtime_display:
            lines.append(tr("tooltip.playtime", playtime=self.game.playtime_display))
        if self.game.last_played_display:
            lines.append(self.game.last_played_display)
        if self.game.is_favorite:
            lines.append(tr("tooltip.favorite"))
        return "\n".join(lines)

    def _setup_shadow_effect(self):
        """Sanfte Hover-Animation: Schatten wächst, Kachel 'schwebt'."""
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(0)
        self._shadow.setOffset(0, 0)
        self._shadow.setColor(QColor(0, 0, 0, 160))
        # Wichtig: Den Shadow-Effekt nur auf den Hintergrund anwenden, 
        # nicht auf die Kinder-Widgets (Icons), um Abschneiden zu verhindern.
        # Da QFrame den Effekt erbt, setzen wir ihn hier, 
        # aber die Icons werden explizit darüber gezeichnet.
        self.setGraphicsEffect(self._shadow)

        self._blur_anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._blur_anim.setDuration(180)
        self._offset_anim = QPropertyAnimation(self._shadow, b"yOffset", self)
        self._offset_anim.setDuration(180)

    def _setup_ui(self, launcher_icons: LauncherIconProvider):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Cover-Bild Container (damit das Icon sauber darüber liegen kann)
        self.cover_container = QFrame(self)
        self.cover_container.setFixedSize(164, 164)
        self.cover_container.setStyleSheet("background: transparent; border: none;")
        
        self.cover_label = QLabel(self.cover_container)
        self.cover_label.setObjectName("game_cover")
        self.cover_label.setFixedSize(164, 164)
        self.cover_label.setAlignment(Qt.AlignCenter)

        cached = self.icon_loader.peek_cover_image(self.game)
        if cached is not None:
            self.cover_label.setPixmap(QPixmap.fromImage(cached))
        else:
            self.cover_label.setPixmap(
                QPixmap.fromImage(self.icon_loader.placeholder_image(self.game))
            )

        # Rundes Launcher-Icon oben links im Cover-Container
        self.launcher_icon_label = QLabel(self.cover_container)
        self.launcher_icon_label.setObjectName("launcher_icon")
        
        # Wir machen das Label etwas größer (28x28) als das Icon (24x24), 
        # damit nichts abgeschnitten wird und ein sauberer Rand entsteht.
        self.launcher_icon_label.setFixedSize(28, 28)
        self.launcher_icon_label.move(6, 6) # Position innerhalb des Covers
        self.launcher_icon_label.setAlignment(Qt.AlignCenter)
        
        # Icon laden und sauber skalieren (KeepAspectRatio)
        icon_image = launcher_icons.get_icon(self.game.launcher_type)
        icon_pixmap = QPixmap.fromImage(icon_image)
        # Skaliere auf 20x20 innerhalb des 28x28 Labels -> kein Abschneiden!
        scaled_pixmap = icon_pixmap.scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.launcher_icon_label.setPixmap(scaled_pixmap)

        # Favoriten-Stern oben rechts im Cover-Container
        self.favorite_badge = QLabel("⭐", self.cover_container)
        self.favorite_badge.setObjectName("favorite_badge")
        self.favorite_badge.setFixedSize(24, 24)
        self.favorite_badge.setAlignment(Qt.AlignCenter)
        self.favorite_badge.move(134, 6) # Rechts oben (164 - 24 - 6)
        if not self.game.is_favorite:
            self.favorite_badge.hide()

        # Reihenfolge ist wichtig: Cover zuerst, dann Overlays
        self.launcher_icon_label.raise_()
        self.favorite_badge.raise_()

        # Game Name
        self.name_label = QLabel(self.game.display_name, self)
        self.name_label.setObjectName("game_name")
        self.name_label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumHeight(34)

        # Launcher Name + Size (z.B. "Steam · 45 GB")
        meta_parts = [self.game.launcher_display_name]
        if self.game.size_display:
            meta_parts.append(self.game.size_display)
        
        self.meta_label = QLabel(" · ".join(meta_parts), self)
        self.meta_label.setObjectName("game_meta")
        self.meta_label.setAlignment(Qt.AlignHCenter)
        self.meta_label.setFixedHeight(16)

        layout.addWidget(self.cover_container, 0, Qt.AlignHCenter)
        layout.addWidget(self.name_label)
        layout.addWidget(self.meta_label)
        layout.addStretch()

    def enterEvent(self, event):
        self._animate_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(False)
        super().leaveEvent(event)

    def _animate_hover(self, hovered: bool):
        self._blur_anim.stop()
        self._offset_anim.stop()
        self._blur_anim.setStartValue(self._shadow.blurRadius())
        self._blur_anim.setEndValue(28 if hovered else 0)
        self._offset_anim.setStartValue(self._shadow.offset())
        self._offset_anim.setEndValue(QPointF(0, 6) if hovered else QPointF(0, 0))
        self._blur_anim.start()
        self._offset_anim.start()

    def _start_cover_loading(self):
        if self.icon_loader.peek_cover_image(self.game) is not None:
            return
        self._worker = _CoverWorker(self.icon_loader, self.game)
        self._worker.signals.finished.connect(self._on_cover_ready)
        QThreadPool.globalInstance().start(self._worker)

    def _on_cover_ready(self, game: Game, image):
        if game is not self.game:
            return
        self.cover_label.setPixmap(QPixmap.fromImage(image))

    def _emit_context(self, pos: QPoint):
        self.context_requested.emit(self.game, self.mapToGlobal(pos))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.game)
        super().mousePressEvent(event)