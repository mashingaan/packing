# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

import gmsh
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

try:
    import OCP  # noqa: F401
except ImportError:
    ocp_binaries = []
    ocp_hiddenimports = []
else:
    ocp_binaries = collect_dynamic_libs("OCP")
    ocp_hiddenimports = collect_submodules("OCP")

project_root = Path.cwd().resolve()
src_root = project_root / "src"
gmsh_module_path = Path(gmsh.__file__).resolve()
gmsh_binary_candidates = [
    gmsh_module_path.with_name("gmsh-4.15.dll"),
    gmsh_module_path.parent.parent / "gmsh-4.15.dll",
]

binaries = [(str(path), ".") for path in gmsh_binary_candidates if path.exists()] + ocp_binaries
datas = []

a = Analysis(
    [str(src_root / "packing_mvp" / "gui.py")],
    pathex=[str(src_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "gmsh",
        "matplotlib.backends.backend_agg",
        "PIL.GifImagePlugin",
        "PIL.Image",
        "tkinter",
        "windnd",
    ] + ocp_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Packing",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
)
