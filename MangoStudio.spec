# -*- mode: python ; coding: utf-8 -*-
# ═══════════════════════════════════════════════════════════
# Mango Studio – PyInstaller-Spec (Windows)
#
# Build:   pyinstaller MangoStudio.spec
# Output:  dist/MangoStudio/MangoStudio.exe
#
# Hinweis: "onedir"-Modus für schnellen Start (keine Entpack-Verzögerung).
# Für eine einzelne .exe ohne dist-Ordner: in der EXE-Sektion
# "exclude_binaries=True" entfernen und "[]" durch a.binaries/a.datas
# ersetzen (onefile) – kostet aber Startzeit.
# Für Debug-Builds mit Terminal/Logging: console=True setzen.
# ═══════════════════════════════════════════════════════════

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Styles, Icons & Assets landen im Bundle-Root und werden
        # von der App über PROJECT_ROOT automatisch gefunden.
        ('assets', 'assets'),
    ],
    hiddenimports=[
        'PySide6.QtNetwork',   # QLocalServer (Single-Instance-Guard)
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'pandas', 'pytest', 'scipy',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MangoStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # True = Terminal-Fenster + Logging sichtbar
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icons/mango.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MangoStudio',
)