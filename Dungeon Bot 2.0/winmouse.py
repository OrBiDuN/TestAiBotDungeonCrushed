"""Small, typed Win32 boundary. Coordinates are physical virtual-desktop pixels."""
import ctypes as C
from ctypes import wintypes as W

user32 = C.WinDLL('user32', use_last_error=True)
kernel32 = C.WinDLL('kernel32', use_last_error=True)
ULONG_PTR = C.c_size_t
LRESULT = C.c_ssize_t
HOOKPROC = C.WINFUNCTYPE(LRESULT, C.c_int, W.WPARAM, W.LPARAM)
ENUMPROC = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)


class MOUSEINPUT(C.Structure):
    _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('mouseData', W.DWORD),
                ('dwFlags', W.DWORD), ('time', W.DWORD), ('dwExtraInfo', ULONG_PTR)]


class KEYBDINPUT(C.Structure):
    _fields_ = [('wVk', W.WORD), ('wScan', W.WORD), ('dwFlags', W.DWORD),
                ('time', W.DWORD), ('dwExtraInfo', ULONG_PTR)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [('uMsg', W.DWORD), ('wParamL', W.WORD), ('wParamH', W.WORD)]


class INPUTUNION(C.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ('data',)
    _fields_ = [('type', W.DWORD), ('data', INPUTUNION)]


class MSLLHOOKSTRUCT(C.Structure):
    _fields_ = [('pt', W.POINT), ('mouseData', W.DWORD), ('flags', W.DWORD),
                ('time', W.DWORD), ('dwExtraInfo', ULONG_PTR)]


def prototype(name, result, *args):
    fn = getattr(user32, name)
    fn.restype, fn.argtypes = result, args
    return fn


prototype('SendInput', W.UINT, W.UINT, C.POINTER(INPUT), C.c_int)
prototype('GetCursorPos', W.BOOL, C.POINTER(W.POINT))
prototype('GetSystemMetrics', C.c_int, C.c_int)
prototype('WindowFromPoint', W.HWND, W.POINT)
prototype('GetAncestor', W.HWND, W.HWND, W.UINT)
prototype('GetForegroundWindow', W.HWND)
prototype('SetForegroundWindow', W.BOOL, W.HWND)
prototype('IsWindow', W.BOOL, W.HWND)
prototype('IsWindowVisible', W.BOOL, W.HWND)
prototype('IsIconic', W.BOOL, W.HWND)
prototype('GetWindowRect', W.BOOL, W.HWND, C.POINTER(W.RECT))
prototype('GetClientRect', W.BOOL, W.HWND, C.POINTER(W.RECT))
prototype('ClientToScreen', W.BOOL, W.HWND, C.POINTER(W.POINT))
prototype('GetDpiForWindow', W.UINT, W.HWND)
prototype('GetWindowThreadProcessId', W.DWORD, W.HWND, C.POINTER(W.DWORD))
prototype('GetWindowTextW', C.c_int, W.HWND, W.LPWSTR, C.c_int)
prototype('GetClassNameW', C.c_int, W.HWND, W.LPWSTR, C.c_int)
prototype('EnumWindows', W.BOOL, ENUMPROC, W.LPARAM)
prototype('SetWindowsHookExW', W.HANDLE, C.c_int, HOOKPROC, W.HINSTANCE, W.DWORD)
prototype('CallNextHookEx', LRESULT, W.HANDLE, C.c_int, W.WPARAM, W.LPARAM)
prototype('UnhookWindowsHookEx', W.BOOL, W.HANDLE)
prototype('GetAsyncKeyState', W.SHORT, C.c_int)
kernel32.GetModuleHandleW.argtypes = [W.LPCWSTR]
kernel32.GetModuleHandleW.restype = W.HMODULE
TAG = 0xDCB200


def enable_dpi():
    prototype('SetProcessDpiAwarenessContext', W.BOOL, W.HANDLE)
    if not user32.SetProcessDpiAwarenessContext(W.HANDLE(-4)):
        # Already set by the host is acceptable; no silent coordinate fallback.
        if C.get_last_error() != 5:
            raise C.WinError(C.get_last_error())


def position():
    point = W.POINT()
    if not user32.GetCursorPos(C.byref(point)):
        raise C.WinError(C.get_last_error())
    return point.x, point.y


def send(flags, x=0, y=0):
    event = INPUT(type=0, mi=MOUSEINPUT(x, y, 0, flags, 0, TAG))
    C.set_last_error(0)
    if user32.SendInput(1, C.byref(event), C.sizeof(INPUT)) != 1:
        raise RuntimeError(f'SendInput отклонён (WinError {C.get_last_error()}). '
                           'Проверьте, не запущено ли целевое окно от администратора.')


def move(x, y):
    left, top, width, height = [user32.GetSystemMetrics(i) for i in (76, 77, 78, 79)]
    if not (left <= x < left + width and top <= y < top + height):
        raise RuntimeError('Точка вне текущего виртуального рабочего стола.')
    # Center of the physical pixel, including negative monitor coordinates.
    nx = min(65535, int((x - left + 0.5) * 65536 / width))
    ny = min(65535, int((y - top + 0.5) * 65536 / height))
    send(0x0001 | 0x8000 | 0x4000, nx, ny)


def root_at(point):
    hwnd = user32.WindowFromPoint(W.POINT(*point))
    return user32.GetAncestor(hwnd, 2)


def rect(hwnd):
    r = W.RECT()
    if not user32.GetWindowRect(hwnd, C.byref(r)):
        raise C.WinError(C.get_last_error())
    return r.left, r.top, r.right, r.bottom


def title(hwnd):
    buf = C.create_unicode_buffer(1024)
    user32.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


def client_rect(hwnd):
    r, p = W.RECT(), W.POINT()
    if not user32.GetClientRect(hwnd, C.byref(r)) or not user32.ClientToScreen(hwnd, C.byref(p)):
        raise C.WinError(C.get_last_error())
    return p.x, p.y, p.x + r.right, p.y + r.bottom


def identity(hwnd):
    pid = W.DWORD()
    if not user32.IsWindow(hwnd) or not user32.GetWindowThreadProcessId(hwnd, C.byref(pid)):
        raise RuntimeError('Окно больше не существует.')
    return hwnd, pid.value


def chrome_windows():
    result = []

    @ENUMPROC
    def callback(hwnd, _):
        buf = C.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, len(buf))
        name = title(hwnd)
        if user32.IsWindowVisible(hwnd) and buf.value == 'Chrome_WidgetWin_1' and 'Google Chrome' in name:
            result.append((hwnd, name))
        return True

    user32.EnumWindows(callback, 0)
    return result


class OneClickRecorder:
    def __init__(self, receive, allow_injected=False):
        self.receive = receive
        self.allow_injected = allow_injected
        self.handle = None
        self.active = False
        self.callback = HOOKPROC(self._callback)

    def start(self):
        self.stop()
        self.handle = user32.SetWindowsHookExW(14, self.callback,
                                              kernel32.GetModuleHandleW(None), 0)
        if not self.handle:
            raise C.WinError(C.get_last_error())
        self.active = True

    def _callback(self, code, message, data):
        if code >= 0 and message == 0x0201 and self.active:
            event = C.cast(data, C.POINTER(MSLLHOOKSTRUCT)).contents
            if self.allow_injected or not event.flags & 1:
                self.active = False
                self.receive((event.pt.x, event.pt.y))
        # Never consume or suppress the original click.
        return user32.CallNextHookEx(self.handle, code, message, data)

    def stop(self):
        self.active = False
        if self.handle:
            if not user32.UnhookWindowsHookEx(self.handle):
                raise C.WinError(C.get_last_error())
            self.handle = None
