"""Restore only this process's disconnected session; never store credentials."""
import ctypes as C
from ctypes import wintypes as W
import os

kernel = C.WinDLL('kernel32', use_last_error=True)
wts = C.WinDLL('wtsapi32', use_last_error=True)
user = C.WinDLL('user32', use_last_error=True)
kernel.ProcessIdToSessionId.argtypes = [W.DWORD, C.POINTER(W.DWORD)]
kernel.ProcessIdToSessionId.restype = W.BOOL
kernel.WTSGetActiveConsoleSessionId.restype = W.DWORD
wts.WTSQuerySessionInformationW.argtypes = [W.HANDLE, W.DWORD, C.c_int, C.POINTER(C.c_void_p), C.POINTER(W.DWORD)]
wts.WTSQuerySessionInformationW.restype = W.BOOL
wts.WTSFreeMemory.argtypes = [C.c_void_p]
wts.WTSConnectSessionW.argtypes = [W.DWORD, W.DWORD, W.LPWSTR, W.BOOL]
wts.WTSConnectSessionW.restype = W.BOOL
user.GetForegroundWindow.restype = W.HWND


def query(session, field):
    pointer, size = C.c_void_p(), W.DWORD()
    if not wts.WTSQuerySessionInformationW(None, session, field, C.byref(pointer), C.byref(size)):
        raise RuntimeError(f'Не удалось прочитать сеанс Windows (код {C.get_last_error()}).')
    try:
        return C.cast(pointer, C.POINTER(C.c_int)).contents.value if field == 8 else C.wstring_at(pointer)
    finally:
        wts.WTSFreeMemory(pointer)


def snapshot():
    session = W.DWORD()
    if not kernel.ProcessIdToSessionId(os.getpid(), C.byref(session)):
        raise RuntimeError('Не удалось определить сеанс бота.')
    return {'session': session.value, 'state': query(session.value, 8),
            'console': kernel.WTSGetActiveConsoleSessionId(),
            'foreground': user.GetForegroundWindow()}


def describe(info=None):
    info = snapshot() if info is None else info
    state = {0: 'подключён', 1: 'подключается', 4: 'отключён (RDP закрыт)'}.get(info['state'], 'недоступен')
    return f"Windows-сеанс {info['session']}: {state}; активное окно: {'есть' if info['foreground'] else 'нет'}."


def request_restore():
    info = snapshot()
    if info['state'] == 0:
        return False
    if info['state'] != 4:
        raise RuntimeError('Восстанавливается только отключённый RDP-сеанс. Дождитесь подключения Windows.')
    source, target = info['session'], info['console']
    if target == 0xffffffff or target == source:
        raise RuntimeError('Локальная консоль пока недоступна. Повторите позже или подключитесь по RDP.')
    # Do not displace another signed-in user, including another session of this user.
    if query(target, 5).strip():
        raise RuntimeError('Локальный экран занят пользовательским сеансом. Автопереключение отменено.')
    if not wts.WTSConnectSessionW(source, target, '', False):
        code = C.get_last_error()
        if code == 5:
            raise RuntimeError('Windows отказала в доступе. Подключитесь по RDP и запустите DungeonBot.exe от имени администратора, затем повторите /desktop.')
        raise RuntimeError(f'Windows не восстановила RDP-сеанс (код {code}). Подключитесь по RDP вручную.')
    return True
