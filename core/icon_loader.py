import ctypes
import hashlib
import json
import logging
import time
import urllib.request
from ctypes import wintypes
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from PySide6.QtCore import QSize, Qt, QRect
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QLinearGradient, QBrush

from core.config import AppConfig
from data.models import Game, LauncherType


class IconLoader:
    """
    Cover-/Icon-Pipeline – thread-sicher durch reine QImage-Verarbeitung.
    Quellen: RAM-Cache → Festplatten-Cache → Steam-Cache → Steam-CDN →
    Online-Suche → Icon-Dateien → eingebettetes .exe-Icon → Platzhalter.
    Hochauflösende Cover werden verlustfrei eingepasst (Letterbox, kein Crop),
    kleine Icons zentriert auf einem Farbverlauf platziert.
    """

    COVER_SIZE = QSize(164, 164)
    CACHE_VERSION = "v5"   # Neue Revision wegen Letterbox-Layout

    def __init__(self, config: AppConfig):
        self.config = config
        self.cache_dir = config.base_dir / "cache" / "icons"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: dict = {}

    # ─── Öffentliche API ──────────────────────────────────────────────────

    def peek_cover_image(self, game: Game) -> Optional[QImage]:
        """Sofortiger Blick in den RAM-Cache (ohne IO, GUI-Thread-sicher)."""
        return self._memory_cache.get(self._cache_key(game))

    def placeholder_image(self, game: Game) -> QImage:
        """Schneller Platzhalter (Buchstabe auf Farbverlauf) für den Sofortaufbau."""
        return self._create_placeholder_image(game)

    def load_cover_image(self, game: Game) -> QImage:
        """
        Lädt das Cover vollständig (Caches, lokale Quellen, Netzwerk).
        Thread-sicher – wird von den Cover-Workern der Kacheln aufgerufen,
        niemals blockierend im GUI-Thread.
        """
        key = self._cache_key(game)
        if key in self._memory_cache:
            return self._memory_cache[key]

        disk_path = self.cache_dir / f"{key}.png"
        if disk_path.exists():
            image = QImage(str(disk_path))
            if not image.isNull():
                self._memory_cache[key] = image
                return image

        image = self._load_from_sources(game)
        if image is None or image.isNull():
            image = self._create_placeholder_image(game)
        else:
            image.save(str(disk_path), "PNG")

        self._memory_cache[key] = image
        return image

    # ─── Quellen ──────────────────────────────────────────────────────────

    def _load_from_sources(self, game: Game) -> Optional[QImage]:
        # A) Vom Scanner gesetzter Pfad
        if game.icon_path and Path(game.icon_path).exists():
            image = QImage(str(game.icon_path))
            if not image.isNull():
                return self._finalize(image, allow_fill=True)

        # B) Steam: lokaler Library-Cache
        image = self._load_steam_cache(game)
        if image is not None:
            return self._finalize(image, allow_fill=True)

        # C) Steam: CDN-Cover via AppID
        if game.launcher_type == LauncherType.STEAM and game.game_id:
            image = self._download_steam_cdn(game.game_id)
            if image is not None:
                return self._finalize(image, allow_fill=True)

        # D) Online-Cover-Suche (launcher-unabhängig)
        image = self._load_online_cover(game)
        if image is not None:
            return self._finalize(image, allow_fill=True)

        # E) Icon-/Bilddateien im Installationsordner
        image = self._load_icon_files(game)
        if image is not None:
            return self._finalize(image, allow_fill=True)

        # F) Eingebettetes .exe-Icon (bis 256 px)
        image = self._extract_exe_icon_highres(game)
        if image is not None:
            return self._finalize(image, allow_fill=False)

        return None

    def _load_steam_cache(self, game: Game) -> Optional[QImage]:
        if game.launcher_type != LauncherType.STEAM or not game.game_id:
            return None
        if not game.install_path:
            return None

        library_root = game.install_path.parent.parent
        cache_dir = library_root / "appcache" / "librarycache"
        if not cache_dir.exists():
            return None

        for suffix in ("_library_600x900.jpg", "_logo.png",
                       "_cover.jpg", "_icon.jpg"):
            candidate = cache_dir / f"{game.game_id}{suffix}"
            if candidate.exists():
                image = QImage(str(candidate))
                if not image.isNull():
                    return image
        return None

    def _download_steam_cdn(self, appid: str) -> Optional[QImage]:
        base = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}"
        for suffix in ("library_600x900.jpg", "header.jpg", "capsule_616x353.jpg"):
            image = self._download_image(f"{base}/{suffix}")
            if image is not None:
                return image
        return None

    def _load_online_cover(self, game: Game) -> Optional[QImage]:
        """Online-Suche über die Steam-Store-Search-API (Fehltreffer-Cache: 7 Tage)."""
        miss_file = self.cache_dir / f"{self._cache_key(game)}.miss"
        if miss_file.exists():
            try:
                if time.time() - miss_file.stat().st_mtime < 7 * 86400:
                    return None
            except OSError:
                pass

        appid = self._search_steam_store_appid(game.display_name)
        if not appid:
            try:
                miss_file.write_text("", encoding="utf-8")
            except OSError:
                pass
            return None

        return self._download_steam_cdn(appid)

    def _search_steam_store_appid(self, name: str) -> Optional[str]:
        try:
            url = ("https://store.steampowered.com/api/storesearch/?term="
                   + quote(name) + "&l=english&cc=US")
            with urllib.request.urlopen(url, timeout=6) as response:
                data = json.loads(response.read().decode("utf-8", errors="ignore"))
            items = data.get("items") or []
            if items:
                return str(items[0].get("id"))
        except Exception:
            return None
        return None

    def _download_image(self, url: str) -> Optional[QImage]:
        try:
            with urllib.request.urlopen(url, timeout=6) as response:
                data = response.read()
            image = QImage.fromData(data)
            return image if not image.isNull() else None
        except Exception:
            return None

    def _load_icon_files(self, game: Game) -> Optional[QImage]:
        if not game.install_path or not game.install_path.exists():
            return None

        patterns = ("*.ico", "icon.png", "icon.jpg", "cover.jpg",
                    "cover.png", "logo.png", "boxart.png")
        for pattern in patterns:
            for candidate in game.install_path.glob(pattern):
                image = QImage(str(candidate))
                if not image.isNull() and max(image.width(), image.height()) >= 48:
                    return image
        return None

    def _extract_exe_icon_highres(self, game: Game) -> Optional[QImage]:
        """Extrahiert das eingebettete Icon in bis zu 256 px (Windows-API)."""
        if not hasattr(QImage, "fromHICON"):
            return None
        if not game.executable_path or not game.executable_path.exists():
            return None
        if game.executable_path.is_dir():
            return None
        try:
            hicon = wintypes.HICON()
            icon_id = wintypes.UINT()
            count = ctypes.windll.user32.PrivateExtractIconsW(
                str(game.executable_path), 0, 256, 256,
                ctypes.byref(hicon), ctypes.byref(icon_id), 1, 0,
            )
            if count > 0 and hicon:
                image = QImage.fromHICON(hicon)
                ctypes.windll.user32.DestroyIcon(hicon)
                if not image.isNull():
                    return image
        except Exception as e:
            logging.debug(f"PrivateExtractIcons fehlgeschlagen für {game.name}: {e}")
        return None

    # ─── Aufbereitung ─────────────────────────────────────────────────────

    def _finalize(self, image: QImage, allow_fill: bool) -> QImage:
        """Crop auf Inhalt → hochauflösend: Letterbox; sonst zentriert auf Cover."""
        image = self._crop_to_content(image)
        dimension = max(image.width(), image.height())
        if allow_fill and dimension >= 256:
            return self._fit_inside(image)
        return self._compose_centered(image)

    def _fit_inside(self, image: QImage) -> QImage:
        """
        Verlustfreies Einpassen: ganzes Cover in die Box skalieren und
        zentrieren (transparente Ränder → Kartenhintergrund scheint durch).
        Ersetzt den alten Crop, der Titel/Logos abgeschnitten hat.
        """
        scaled = image.scaled(
            self.COVER_SIZE,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        canvas = QImage(self.COVER_SIZE, QImage.Format_ARGB32)
        canvas.fill(Qt.transparent)

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        x = (self.COVER_SIZE.width() - scaled.width()) // 2
        y = (self.COVER_SIZE.height() - scaled.height()) // 2
        painter.drawImage(x, y, scaled)
        painter.end()
        return canvas

    def _compose_centered(self, image: QImage) -> QImage:
        """Setzt ein (kleines) Icon sauber zentriert auf einen Farbverlauf-Cover."""
        native = max(image.width(), image.height())
        if native >= 256:
            target = 140
        else:
            target = min(112, max(64, native * 2))

        scaled = image.scaled(
            QSize(target, target),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )

        canvas = QImage(self.COVER_SIZE, QImage.Format_ARGB32)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing)

        gradient = QLinearGradient(0, 0, 0, self.COVER_SIZE.height())
        gradient.setColorAt(0, QColor("#3a3a5c"))
        gradient.setColorAt(1, QColor("#24243a"))
        painter.fillRect(canvas.rect(), QBrush(gradient))

        x = (self.COVER_SIZE.width() - scaled.width()) // 2
        y = (self.COVER_SIZE.height() - scaled.height()) // 2
        painter.drawImage(x, y, scaled)
        painter.end()
        return canvas

    def _crop_to_content(self, image: QImage) -> QImage:
        """Schneidet transparente Ränder ab (Alpha-Bounding-Box)."""
        if not image.hasAlphaChannel():
            return image

        image = image.convertToFormat(QImage.Format_RGBA8888)
        width, height = image.width(), image.height()
        try:
            buf = image.constBits().tobytes()
        except Exception:
            return image

        stride = width * 4
        min_x, min_y, max_x, max_y = width, height, -1, -1

        for y in range(height):
            alphas = buf[y * stride + 3: (y + 1) * stride: 4]
            indexes = [i for i, a in enumerate(alphas) if a > 8]
            if not indexes:
                continue
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y
            if indexes[0] < min_x:
                min_x = indexes[0]
            if indexes[-1] > max_x:
                max_x = indexes[-1]

        if max_x < 0 or max_y < 0:
            return image

        rect = QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
        return image.copy(rect)

    def _create_placeholder_image(self, game: Game) -> QImage:
        """Platzhalter: Anfangsbuchstaben auf Farbverlauf."""
        canvas = QImage(self.COVER_SIZE, QImage.Format_ARGB32)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing)

        gradient = QLinearGradient(0, 0, 0, self.COVER_SIZE.height())
        gradient.setColorAt(0, QColor("#3a3a5c"))
        gradient.setColorAt(1, QColor("#24243a"))
        painter.fillRect(canvas.rect(), QBrush(gradient))

        letter = game.display_name.strip()[:2].upper() or "?"
        painter.setPen(QColor("#d8d8f0"))
        painter.setFont(QFont("Segoe UI", 52, QFont.Bold))
        painter.drawText(canvas.rect(), Qt.AlignCenter, letter)
        painter.end()
        return canvas

    def _cache_key(self, game: Game) -> str:
        raw = f"{game.name}|{game.launcher_type.name}|{self.CACHE_VERSION}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()