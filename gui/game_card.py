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
    Spiele-Kachel mit Cover, rundem Launcher-Icon-Overlay, Favoriten-Stern,
    Name, Spielzeit und sanfter Hover-Schattenanimation.
    """
    clicked = Signal(Game)
    context_requested = Signal(Game, QPoint)

    CARD_WIDTH = 180
    CARD_HEIGHT = 250

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

    # ─── Aufbau ───────────────────────────────────────────────────────────

    def _build_tooltip(self) -> str:
        lines = [self.game.display_name,
                 tr("tooltip.launcher", launcher=self.game.launcher_display_name)]
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
        self.setGraphicsEffect(self._shadow)

        self._blur_anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._blur_anim.setDuration(180)
        self._offset_anim = QPropertyAnimation(self._shadow, b"yOffset", self)
        self._offset_anim.setDuration(180)

    def _setup_ui(self, launcher_icons: LauncherIconProvider):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        self.cover_label = QLabel(self)
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

        # Rundes Launcher-Icon oben links (statt Namens-Badge)
        self.launcher_icon_label = QLabel(self)
        self.launcher_icon_label.setObjectName("launcher_icon")
        self.launcher_icon_label.setFixedSize(32, 32)
        self.launcher_icon_label.move(10, 10)
        self.launcher_icon_label.setPixmap(
            QPixmap.fromImage(launcher_icons.get_icon(self.game.launcher_type))
        )

        # Favoriten-Stern oben rechts
        self.favorite_badge = QLabel("⭐", self)
        self.favorite_badge.setObjectName("favorite_badge")
        self.favorite_badge.move(146, 10)
        if not self.game.is_favorite:
            self.favorite_badge.hide()

        self.launcher_icon_label.raise_()
        self.favorite_badge.raise_()

        self.name_label = QLabel(self.game.display_name, self)
        self.name_label.setObjectName("game_name")
        self.name_label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumHeight(34)

        self.meta_label = QLabel(self)
        self.meta_label.setObjectName("game_meta")
        self.meta_label.setAlignment(Qt.AlignHCenter)
        self.meta_label.setFixedHeight(16)
        if self.game.playtime_display:
            self.meta_label.setText(f"⏱ {self.game.playtime_display}")
        else:
            self.meta_label.hide()

        layout.addWidget(self.cover_label, 0, Qt.AlignHCenter)
        layout.addWidget(self.name_label)
        layout.addWidget(self.meta_label)

    # ─── Hover-Animation ──────────────────────────────────────────────────

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

    # ─── Cover-Loading & Events ───────────────────────────────────────────

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