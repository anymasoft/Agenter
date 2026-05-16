# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('ui', 'ui'), ('..\\scripts', 'scripts')],
    hiddenimports=[
        # pywebview WinForms backend
        'webview',
        'webview.platforms.winforms',
        'webview.platforms.edgechromium',
        'clr_loader',
        'pythonnet',
        # pystray Windows backend
        'pystray',
        'pystray._win32',
        # asyncio / websockets
        'websockets',
        'websockets.legacy',
        'websockets.legacy.client',
        'aiohttp',
        # PIL
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Agenter Desktop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # без консольного окна
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
