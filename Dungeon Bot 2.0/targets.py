"""Read-only Steam process/window discovery. No injection or process memory access."""
from pathlib import Path
import psutil
import winmouse as win

STEAM_EXE = Path(r'C:\Program Files (x86)\Steam\steamapps\common\Dungeon Crusher Soul Hunters\dungeoncrusher.exe')


def launch_game():
    import subprocess
    if not STEAM_EXE.is_file():
        raise RuntimeError('Не найден установленный Dungeon Crusher: ' + str(STEAM_EXE))
    subprocess.Popen([str(STEAM_EXE)], cwd=str(STEAM_EXE.parent))


def steam_windows():
    processes = {}
    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        try:
            if (proc.info['name'] or '').casefold() == 'dungeoncrusher.exe':
                processes[proc.pid] = proc.info['exe'] or '(путь недоступен)'
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    windows = []

    @win.ENUMPROC
    def visit(hwnd, _):
        if not win.user32.IsWindowVisible(hwnd):
            return True
        try:
            _, pid = win.identity(hwnd)
            if pid in processes:
                l, t, r, b = win.client_rect(hwnd)
                if (r > l and b > t) or win.user32.IsIconic(hwnd):
                    windows.append(dict(hwnd=hwnd, pid=pid, title=win.title(hwnd),
                                        path=processes[pid], width=r-l, height=b-t))
        except (RuntimeError, OSError):
            pass
        return True

    win.user32.EnumWindows(visit, 0)
    windows.sort(key=lambda item: item['width']*item['height'], reverse=True)
    return processes, windows
