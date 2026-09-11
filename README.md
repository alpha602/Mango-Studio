# 🥭 Mango Studio 1.0

**Your central game hub for Windows.**

Mango Studio lists all installed games on your PC in one place, 
regardless of which launcher they were installed through.
Search, click, play. No more opening six different launchers to find one game.

---
<img width="1919" height="1030" alt="Screenshot 2026-09-11 205726" src="https://github.com/user-attachments/assets/2abbbf86-d6dc-410b-bd05-19d80bbf9f35" />

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

## ❕Important - Read before usage
- This is an Open Source Project, means you can, at anytime, look at every File yourself and determine if you want to use it.
- This Programm does nothing more than just looking for directories of Launchers, looking into the files and searching for the Games itself. (All Launchers and where it searches exactly are listed right above this)
- What it doesnt do: Change your Games, messes with your Savefiles, re-writing Directories or Files directly, getting you banned in online games
- If you stumble across any Errors or Bugs that i havent listed in "Current Issues / Future Plans", either open an Issue, or contact me on Discord - fiddlesticksz (Please note that im not very active on Discord)

## ⚠️ Current issues / Future Plans
- Issues: App starts with the Main Language as German
- Issues: First ever Scan after Startup doesnt scan properly sometimes
- Issues: Formatting is slightly off when switching between "All" and seperate Launchers tab
- Issues: Launcher Icons have a weird shadow inside of them
---
- Future Plans: Fix all appearing Issues (obviously)
- Future Plans: Add more Languages (French and Spanish is currently planned)
- Future Plans: Make the UI/UX more appealing
- Future Plans: Add option to Hide Standalone Games from manually added Directories in the Main Panel, but still being able to search for the Games
- Future Plans: Make the Settings tab integrated instead of a Popup
- Future Plans: Add more Settings Options
- Future Plans: Add more Launcher Options

---

# 🚀 How to Install 
## 1. Exe Standalone Install (Use this if you have Python installed)
1. Simply open a Terminal
2. Make sure your Terminal is in the same directory where the files are located - cd "C:\Downloads\Mango Studio" - as example
3. Type and run "pip install pyinstaller"
4. Type and run "pyinstaller MangoStudio.spec"
5. Wait for full install - the .exe will be placed in the "dist" Folder

## 2. Exe Standalone Install (Use this if you dont have python on your PC)
1. Locate the Folder
2. Run the .bat File
3. The .bat will install all needed Files by itself
4. Wait for full install - the .exe will be placed in the "dist" Folder

## 3. Proper Start (Run without Exe)

```bash
# 1) Install dependencies
pip install -r Requirements.txt

# 2) Start the app (Can take a few Seconds on first start)
python main.py

# Optional: Force a full scan (or just use the built-in "Refresh" Button at the Top)
python main.py --rescan

