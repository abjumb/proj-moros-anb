# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Windows build of mDiscovery.

Build from the repository root:

    pyinstaller packaging/mdiscovery.spec --noconfirm

Produces dist/mDiscovery/ (onedir — QtWebEngine ships its own renderer
process and resource files, which onedir handles far more reliably than
onefile). Resources resolve at runtime via mdiscovery.resources, which
checks the executable directory and sys._MEIPASS.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent  # packaging/ -> repo root

# kuzu is a native extension; make sure its shared library lands in the bundle.
kuzu_datas, kuzu_binaries, kuzu_hidden = collect_all("kuzu")

a = Analysis(
    [str(ROOT / "packaging" / "launch.py")],
    pathex=[str(ROOT / "src")],
    binaries=kuzu_binaries,
    datas=[(str(ROOT / "assets"), "assets")] + kuzu_datas,
    hiddenimports=kuzu_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mDiscovery",
    icon=str(ROOT / "assets" / "windows" / "mdiscovery.ico"),
    console=False,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="mDiscovery",
)
