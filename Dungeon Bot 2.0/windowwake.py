"""Bounded native activation, without clicks, keystrokes or permanent topmost flags."""
import ctypes as C
from ctypes import wintypes as W
import time
import winmouse as win

win.prototype('ShowWindowAsync', W.BOOL, W.HWND, C.c_int)
win.prototype('BringWindowToTop', W.BOOL, W.HWND)


class WindowWake:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.owner = win.identity(hwnd)
        self.started = time.perf_counter()
        self.deadline = self.started + 4
        self.next_attempt = 0
        self.attempts = 0
        self.stable_since = None
        self.ready_at = None

    def poll(self):
        now = time.perf_counter()
        if win.identity(self.hwnd) != self.owner:
            raise RuntimeError('Окно для пробуждения закрыто или заменено.')
        if not win.user32.IsIconic(self.hwnd) and win.user32.GetForegroundWindow() == self.hwnd:
            self.stable_since = self.stable_since or now
            if now-self.stable_since >= .2:
                self.ready_at = self.ready_at or now
                return True
            return False
        self.stable_since = None
        self.ready_at = None
        if now > self.deadline:
            raise RuntimeError(f'Не удалось пробудить HWND {self.hwnd}: активное окно '
                               f'{win.user32.GetForegroundWindow()}. Клик не выполнен.')
        if now < self.next_attempt or self.attempts >= 3:
            return False
        self.attempts += 1
        self.next_attempt = now + .7
        if win.user32.IsIconic(self.hwnd):
            win.user32.ShowWindowAsync(self.hwnd, 9)  # SW_RESTORE, preserve normal placement.
        win.user32.BringWindowToTop(self.hwnd)
        win.user32.SetForegroundWindow(self.hwnd)
        if win.user32.GetForegroundWindow() == self.hwnd:
            return False
        # Foreground changes across input queues are asynchronous. Poll on later
        # Qt ticks; don't join input queues (which can hang the GUI on a busy game).
        return False
