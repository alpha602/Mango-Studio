"""Leichtgewichtiges Übersetzungssystem (DE/EN) für die Mango-Studio-UI."""
import logging

_TRANSLATIONS = {
    "de": {
        "app.title": "Mango Studio",
        "app.subtitle": "Dein Spiele-Hub",
        "search.placeholder": "🔍  Suche nach Spielen... (z. B. 'The Witcher', 'Cyberpunk', 'Hades')",
        "button.refresh": "🔄 Aktualisieren",
        "button.settings": "⚙ Einstellungen",
        "status.loading": "Lade Spiele...",
        "status.scanning": "Scanne nach installierten Spielen...",
        "status.scan_done": "✅ Scan abgeschlossen: {count} Spiele gefunden in {seconds:.1f}s",
        "status.scan_error": "❌ Fehler beim Scannen aufgetreten.",
        "status.library": "📚 {count} Spiele in der Bibliothek",
        "status.filter": "🔍 {count} Spiele (Filter: {filter}{search})",
        "status.launching": "🚀 {name} wird gestartet...",
        "status.session_end": "⏱ {name}: Session beendet (+{minutes} min Spielzeit)",
        "status.hidden": "🙈 '{name}' wurde verborgen.",
        "status.fav_on": "⭐ '{name}' ist jetzt ein Favorit.",
        "status.fav_off": "💔 '{name}' ist kein Favorit mehr.",
        "empty.games": "🎮 Keine Spiele gefunden.",
        "section.favorites": "⭐ Favoriten",
        "section.all": "📚 Alle Spiele",
        "filter.all": "Alle",
        "menu.start": "🚀 Spiel starten",
        "menu.fav_add": "⭐ Als Favorit markieren",
        "menu.fav_remove": "💔 Favorit entfernen",
        "menu.folder": "📁 Ordner öffnen",
        "menu.launcher": "🏷 Launcher anzeigen",
        "menu.hide": "🙈 Verbergen",
        "dlg.scan_title": "Scan-Fehler",
        "dlg.scan_text": "Beim Scannen ist ein Fehler aufgetreten:\n{error}",
        "dlg.db_title": "Datenbank-Fehler",
        "dlg.db_text": ("Die Spiele-Bibliothek konnte nicht geladen werden.\n"
                        "Ein Klick auf 'Aktualisieren' baut die Bibliothek neu auf.\n\nDetails: {error}"),
        "dlg.missing_title": "Spiel nicht gefunden",
        "dlg.missing_text": ("Die ausführbare Datei wurde nicht gefunden:\n{path}\n\n"
                             "Das Spiel wurde möglicherweise deinstalliert oder verschoben."),
        "dlg.start_title": "Start-Fehler",
        "dlg.start_text": "Das Spiel konnte nicht gestartet werden:\n{name}",
        "dlg.folder_missing": "Ordner nicht gefunden",
        "dlg.folder_missing_text": "Der Installationsordner existiert nicht mehr.",
        "dlg.error": "Fehler",
        "dlg.error_folder": "Ordner konnte nicht geöffnet werden:\n{error}",
        "dlg.error_hide": "'{name}' konnte nicht verborgen werden.",
        "dlg.error_fav": "Favoriten-Status von '{name}' konnte nicht geändert werden.",
        "info.title": "Launcher-Information",
        "info.game": "Spiel",
        "info.launcher": "Launcher",
        "info.status": "Status",
        "info.status_running": "🟢 läuft gerade",
        "info.status_stopped": "⚪ nicht gestartet",
        "info.favorite": "Favorit",
        "info.favorite_yes": "⭐ Ja",
        "info.favorite_no": "Nein",
        "info.playtime": "Spielzeit",
        "info.path": "Installationspfad",
        "info.unknown": "Unbekannt",
        "info.command": "Startbefehl",
        "tooltip.launcher": "Launcher: {launcher}",
        "tooltip.playtime": "Spielzeit: {playtime}",
        "tooltip.favorite": "⭐ Favorit",
        "settings.title": "Einstellungen",
        "settings.tab_general": "Allgemein",
        "settings.tab_folders": "Scan-Ordner",
        "settings.tab_hidden": "Verborgene Spiele",
        "settings.language": "Sprache:",
        "settings.tray": "Beim Schließen in den System-Tray minimieren",
        "settings.autostart": "Mit Windows starten (Autostart)",
        "settings.folders.add": "➕ Ordner hinzufügen",
        "settings.folders.remove": "➖ Entfernen",
        "settings.folders.hint": ("Zusätzliche Ordner, die nach Spielen durchsucht werden.\n"
                                   "Jeder Unterordner (oder der Ordner selbst) mit .exe gilt als Spiel."),
        "settings.hidden.empty": "Keine verborgenen Spiele.",
        "settings.hidden.show": "👁 Sichtbar machen",
        "tray.show": "🥭 Mango Studio öffnen",
        "tray.scan": "🔄 Scan starten",
        "tray.quit": "❌ Beenden",
    },
    "en": {
        "app.title": "Mango Studio",
        "app.subtitle": "Your game hub",
        "search.placeholder": "🔍  Search games... (e.g. 'The Witcher', 'Cyberpunk', 'Hades')",
        "button.refresh": "🔄 Refresh",
        "button.settings": "⚙ Settings",
        "status.loading": "Loading games...",
        "status.scanning": "Scanning for installed games...",
        "status.scan_done": "✅ Scan finished: {count} games found in {seconds:.1f}s",
        "status.scan_error": "❌ An error occurred while scanning.",
        "status.library": "📚 {count} games in library",
        "status.filter": "🔍 {count} games (filter: {filter}{search})",
        "status.launching": "🚀 Launching {name}...",
        "status.session_end": "⏱ {name}: session ended (+{minutes} min playtime)",
        "status.hidden": "🙈 '{name}' has been hidden.",
        "status.fav_on": "⭐ '{name}' is now a favorite.",
        "status.fav_off": "💔 '{name}' is no longer a favorite.",
        "empty.games": "🎮 No games found.",
        "section.favorites": "⭐ Favorites",
        "section.all": "📚 All games",
        "filter.all": "All",
        "menu.start": "🚀 Launch game",
        "menu.fav_add": "⭐ Mark as favorite",
        "menu.fav_remove": "💔 Remove favorite",
        "menu.folder": "📁 Open folder",
        "menu.launcher": "🏷 Show launcher",
        "menu.hide": "🙈 Hide",
        "dlg.scan_title": "Scan error",
        "dlg.scan_text": "An error occurred while scanning:\n{error}",
        "dlg.db_title": "Database error",
        "dlg.db_text": ("The game library could not be loaded.\n"
                        "Click 'Refresh' to rebuild the library.\n\nDetails: {error}"),
        "dlg.missing_title": "Game not found",
        "dlg.missing_text": ("The executable was not found:\n{path}\n\n"
                             "The game may have been uninstalled or moved."),
        "dlg.start_title": "Launch error",
        "dlg.start_text": "The game could not be launched:\n{name}",
        "dlg.folder_missing": "Folder not found",
        "dlg.folder_missing_text": "The install folder no longer exists.",
        "dlg.error": "Error",
        "dlg.error_folder": "Folder could not be opened:\n{error}",
        "dlg.error_hide": "'{name}' could not be hidden.",
        "dlg.error_fav": "Favorite state of '{name}' could not be changed.",
        "info.title": "Launcher information",
        "info.game": "Game",
        "info.launcher": "Launcher",
        "info.status": "Status",
        "info.status_running": "🟢 running",
        "info.status_stopped": "⚪ not started",
        "info.favorite": "Favorite",
        "info.favorite_yes": "⭐ Yes",
        "info.favorite_no": "No",
        "info.playtime": "Playtime",
        "info.path": "Install path",
        "info.unknown": "Unknown",
        "info.command": "Launch command",
        "tooltip.launcher": "Launcher: {launcher}",
        "tooltip.playtime": "Playtime: {playtime}",
        "tooltip.favorite": "⭐ Favorite",
        "settings.title": "Settings",
        "settings.tab_general": "General",
        "settings.tab_folders": "Scan folders",
        "settings.tab_hidden": "Hidden games",
        "settings.language": "Language:",
        "settings.tray": "Minimize to system tray on close",
        "settings.autostart": "Start with Windows (autostart)",
        "settings.folders.add": "➕ Add folder",
        "settings.folders.remove": "➖ Remove",
        "settings.folders.hint": ("Additional folders scanned for games.\n"
                                  "Every subfolder (or the folder itself) containing an .exe counts as a game."),
        "settings.hidden.empty": "No hidden games.",
        "settings.hidden.show": "👁 Unhide",
        "tray.show": "🥭 Open Mango Studio",
        "tray.scan": "🔄 Start scan",
        "tray.quit": "❌ Quit",
    },
}

_current_language = "de"


def set_language(language: str):
    """Setzt die aktive UI-Sprache ('de' oder 'en')."""
    global _current_language
    if language in _TRANSLATIONS:
        _current_language = language
    else:
        logging.warning(f"Unbekannte Sprache '{language}' – bleibe bei '{_current_language}'.")


def get_language() -> str:
    return _current_language


def tr(key: str, **kwargs) -> str:
    """Gibt den übersetzten Text für einen Schlüssel zurück (mit Formatierung)."""
    table = _TRANSLATIONS.get(_current_language, _TRANSLATIONS["de"])
    text = table.get(key) or _TRANSLATIONS["de"].get(key) or key
    return text.format(**kwargs) if kwargs else text