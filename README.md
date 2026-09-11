# 🥭 Mango Studio 1.0

**Your central game hub for Windows.**

Mango Studio lists all installed games on your PC in one place, 
regardless of which launcher they were installed through.
Search, click, play. No more opening six different launchers to find one game.

---

## ✨ Features

- **Central library** across all launchers (including external hard drives)
- **Custom scan folders** for standalone games without a launcher
- **Real-time search** (normalized: umlauts/dots/hyphens don't matter) + Enter launches the top result
- **Launcher filter chips** („All | Steam (24) | Epic (3) | …")
- **1-click launch**: Deep links for launcher games, direct `.exe` for standalone
- **High-quality covers**: Steam cache & Steam CDN, online cover search,
  embedded `.exe` icons, stylish placeholders – fully cached & loaded asynchronously
- **Real launcher logos** as round overlays on every tile
- **Playtime tracking** & „Last played" for directly launched games
- **Favorites** with their own section at the top of the grid (⭐ badge, context menu toggle)
- **Launcher live status** (🟢 running /  not started) via process list
- **Context menu**: Launch, Favorite, Open folder, Launcher info, Hide
- **Manage hidden games** (Settings → Tab „Hidden Games")
- **Settings dialog**: Language (DE/EN), Tray behavior, Autostart, Scan folders
- **System tray** with menu + optional „Minimize to tray"
- **Autostart option** (Windows Registry, via checkbox)
- **Responsive cover grid**, smooth hover animation, dark theme (external QSS)
- **Scan only on first start**, manually via button or `--rescan` – in a background thread
- **Robust**: Single-instance guard, persistent settings, WAL database with schema versioning

---

## 🎮 Supported Launchers & Detection Methods

| Launcher        | Detection                                                                 |
|-----------------|---------------------------------------------------------------------------|
| Steam           | `appmanifest_*.acf` + `libraryfolders.vdf` (all libraries/drives)         |
| Epic Games      | Launcher manifests (`*.item` JSON, excluding DLCs), Fallback: Folder walk |
| GOG             | Windows Registry (`GOG.com\Games`, incl. gameID), Fallback: Folder walk   |
| Battle.net      | Standard paths on all drives                                              |
| EA App / Origin | Standard paths on all drives                                              |
| Ubisoft Connect | Standard paths on all drives                                              |
| Xbox / MS Store | `XboxGames` folder                                                        |
| Riot Games      | Standard paths on all drives                                              |
| Gaijin.net      | Standard paths on all drives                                              |
| Amazon Games    | Standard paths on all drives                                              |
| itch.io         | AppData installation folder                                               |
| Standalone      | Custom scan folders (recursive .exe scan with junk filter)                |

---

## 🧰 Requirements

- **Operating System:** Windows 10 / 11
- **Python:** 3.9 or newer (recommended: 3.12)
- **Dependency:** PySide6 (see `requirements.txt`)

---

## ⚠️ Current issues / Future Plans
- Issues: App starts with the Main Language as German
- Issues: Before the first mannual Scan-refresh, not all Games get always listed
- Issues: Formatting is slightly off when switching between "All" and seperate Launchers tab
- Issues: Launcher Icons have a weird shadow inside of them
- Future Plans: Fix all appearing Issues (obviously)
- Future Plans: Add more Languages (French and Spanish is currently planned)
- Future Plans: Make the UI/UX more appealing
- Future Plans: Make the Settingstab integrated instead of a Pop UP
- Future Plans: Add more Settings Options
- Future Plans: Add more Launcher Options

---

## 🚀 Installation & Start (Development)

```bash
# 1) Install dependencies
pip install -r requirements.txt

# 2) (Optional, one-time) Generate app icon
python generate_icon.py

# 3) Start the app
python main.py

# Optional: Force a full scan
python main.py --rescan


