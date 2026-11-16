from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH)
capture_data, capture_binaries, capture_imports = collect_all('windows_capture')
winrt_data, winrt_binaries, winrt_imports = collect_all('winrt')
a = Analysis(
    [str(root / 'exe_entry.py')], pathex=[str(root)],
    binaries=capture_binaries + winrt_binaries,
    datas=[(str(root / 'assets'), 'assets')] + capture_data + winrt_data,
    hiddenimports=capture_imports + winrt_imports + collect_submodules('winrt'),
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='DungeonBot',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
