# PyInstaller build of the engine: a folder with clipping-engine.exe that the desktop app ships.
# Build with: node scripts/build-engine.mjs (from the project root)
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

datas = [("models", "models")]
datas += collect_data_files("faster_whisper")  # voice-activity model used during transcription

binaries = collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("onnxruntime")

hiddenimports = (
    collect_submodules("uvicorn")  # uvicorn loads its protocol and loop implementations by name
    + collect_submodules("app")
    + ["faster_whisper", "ctranslate2", "cv2"]  # imported lazily inside functions
)

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "torch"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="clipping-engine",
    console=True,  # stdout is how the app learns the engine is ready; the app hides the window
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="clipping-engine", upx=False)
