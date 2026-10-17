# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('data\\*.py', 'data'), ('data\\exoplanets.csv', 'data'), ('data\\hipparcos.csv', 'data'), ('core\\*.py', 'core'), ('scene\\*.py', 'scene'), ('ui\\*.py', 'ui'), ('assets\\app.png', 'assets'), ('assets\\app.ico', 'assets')],
    hiddenimports=['PyQt5.QtOpenGL', 'PyQt5.QtWidgets', 'matplotlib.backends.backend_qt5agg', 'scipy.optimize', 'scipy.signal'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision', 'torchaudio', 'tensorboard', 'tensorflow', 'tkinter', 'pytest', 'IPython', 'jupyter', 'notebook', 'PySide6', 'PySide2', 'PyQt6', 'wx', '_ssl_ca_certs'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Astrarium',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\app.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Astrarium',
)
