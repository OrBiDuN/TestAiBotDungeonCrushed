"""WGC by HWND. One latest owned QImage, no per-frame Qt signals or disk writes."""
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass, replace
import threading
import time
from collections import deque

from PySide6.QtCore import QThread
from PySide6.QtGui import QImage
import winmouse as win


@dataclass(frozen=True)
class VideoFrame:
    image: QImage
    sequence: int
    received: float
    wall_time: float
    copy_ms: float
    source_age_ms: float | None


class LiveCapture(QThread):
    def __init__(self, hwnd, area=None, fps=15, parent=None):
        super().__init__(parent)
        self.hwnd = hwnd
        self.owner = win.identity(hwnd)
        self.area = replace(area) if area else None
        self.target_fps = fps
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frame = None
        self._count = 0
        self._first = self._last = 0.0
        self._copy_total = self._age_total = 0.0
        self._age_count = 0
        self._state = 'Запуск WGC…'
        self._error = None
        self._last_publish = 0.0
        self._times = deque(maxlen=60)  # Timestamps only, never a frame queue.

    def request_stop(self):
        self._stop.set()
        with self._lock:
            self._frame = None
            if not self._error:
                self._state = 'Остановка…'

    def latest_frame(self):
        """Future vision consumers may read this single slot; do not mutate image."""
        with self._lock:
            return self._frame

    def snapshot(self):
        with self._lock:
            elapsed = self._times[-1]-self._times[0] if len(self._times) > 1 else 0
            return dict(count=self._count, fps=(len(self._times)-1)/elapsed if elapsed > 0 else 0,
                        copy_ms=self._copy_total/max(1, self._count),
                        source_age_ms=self._age_total/self._age_count if self._age_count else None,
                        state=self._state, error=self._error, last=self._last)

    def fail(self, exc):
        with self._lock:
            self._error = str(exc)
            self._state = 'Ошибка: ' + str(exc)
            self._frame = None
        self._stop.set()

    def validate(self):
        if win.identity(self.hwnd) != self.owner:
            raise RuntimeError('Выбранное окно закрыто или заменено.')
        if win.user32.IsIconic(self.hwnd):
            raise RuntimeError('Окно свёрнуто. Разверните его и запустите трансляцию снова.')
        if self.area:
            self.area.rectangle()  # Existing calibration owns size/DPI/title policy.

    def crop_origin(self, width, height):
        # WGC captures the visible DWM frame, not necessarily GetWindowRect's shadow.
        client = win.client_rect(self.hwnd)
        extended = W.RECT()
        dwm = C.WinDLL('dwmapi')
        dwm.DwmGetWindowAttribute.argtypes = [W.HWND, W.DWORD, C.c_void_p, W.DWORD]
        dwm.DwmGetWindowAttribute.restype = W.LONG
        candidates = []
        if dwm.DwmGetWindowAttribute(self.hwnd, 9, C.byref(extended), C.sizeof(extended)) == 0:
            candidates.append((extended.left, extended.top, extended.right, extended.bottom))
        candidates.extend((win.rect(self.hwnd), client))
        for l, t, r, b in candidates:
            if (r-l, b-t) == (width, height):
                x, y, w, h = self.area.crop
                return client[0]-l+x, client[1]-t+y, w, h
        raise RuntimeError(f'Размер WGC {width}×{height} не совпал с геометрией окна; '
                           'остановлено без предположений о смещении калибровки.')

    def receive(self, frame, internal):
        if self._stop.is_set():
            internal.stop()
            return
        start = time.perf_counter()
        if win.user32.IsIconic(self.hwnd):
            return
        if start-self._last_publish < 0.95/self.target_fps:
            return
        try:
            self.validate()
            pixels = frame.frame_buffer
            if self.area:
                x, y, w, h = self.crop_origin(frame.width, frame.height)
                if min(x, y) < 0 or x+w > frame.width or y+h > frame.height:
                    raise RuntimeError('Калибровка выходит за границы кадра WGC.')
                pixels = pixels[y:y+h, x:x+w]
            # Copy from native mapped memory BEFORE callback returns; never retain GPU buffers.
            import numpy as np
            pixels = np.ascontiguousarray(pixels)
            h, w, _ = pixels.shape
            image = QImage(pixels.data, w, h, pixels.strides[0], QImage.Format_ARGB32).copy()
            end = time.perf_counter()
            age = (end-frame.timespan/10_000_000)*1000
            age = age if 0 <= age < 10000 else None
            with self._lock:
                if self._stop.is_set():
                    return
                self._count += 1
                if self._count == 1:
                    self._first = end
                self._last = end
                self._times.append(end)
                self._last_publish = start
                copy_ms = (end-start)*1000
                self._copy_total += copy_ms
                if age is not None:
                    self._age_total += age
                    self._age_count += 1
                self._frame = VideoFrame(image, self._count, end, time.time(), copy_ms, age)
                self._state = 'Трансляция WGC'
        except Exception as exc:
            if win.user32.IsIconic(self.hwnd) and win.user32.IsWindow(self.hwnd):
                return  # Window minimized between the precheck and geometry read.
            self.fail(exc)
            internal.stop()

    def run(self):
        control = capture = None
        try:
            from windows_capture import WindowsCapture
            while win.user32.IsIconic(self.hwnd) and not self._stop.is_set():
                with self._lock:
                    self._state = 'Пауза: выбранное окно свёрнуто. Ожидание разворачивания.'
                self._stop.wait(0.1)
            if self._stop.is_set():
                return
            self.validate()
            # MinimumUpdateInterval is absent on some supported Windows builds.
            # Throttle before copying in receive(), keeping WGC itself compatible.
            capture = WindowsCapture(window_hwnd=self.hwnd, cursor_capture=False)
            capture.frame_handler = self.receive
            capture.closed_handler = lambda: self.fail(RuntimeError('WGC: целевое окно закрыто.'))
            control = capture.start_free_threaded()
            started = time.perf_counter()
            while not self._stop.wait(0.1):
                if win.identity(self.hwnd) != self.owner:
                    raise RuntimeError('Выбранное окно закрыто или заменено.')
                if win.user32.IsIconic(self.hwnd):
                    with self._lock:
                        self._frame = None
                        self._times.clear()
                        self._state = 'Пауза: окно свёрнуто. Поток продолжится после разворачивания.'
                    started = time.perf_counter()  # No first-frame timeout while minimized.
                    continue
                self.validate()
                if control.is_finished():
                    control.wait()  # Propagate callback/native failures.
                    raise RuntimeError('Сеанс WGC завершился неожиданно.')
                snap = self.snapshot()
                if snap['count'] == 0 and time.perf_counter()-started > 8:
                    raise RuntimeError('WGC не передал ни одного кадра за 8 секунд. '
                                       'Возможны запрет захвата окна, свёрнутое окно или недоступный графический сеанс.')
                if snap['last'] and time.perf_counter()-snap['last'] > 2:
                    with self._lock:
                        self._state = 'Нет новых кадров WGC более 2 с (статичное/недоступное окно)'
        except Exception as exc:
            self.fail(exc)
        finally:
            if control is not None:
                try:
                    control.stop()  # Joining native capture happens OFF the GUI thread.
                except Exception as exc:
                    self.fail(exc)
            if capture is not None:
                capture.frame_handler = capture.closed_handler = None
            with self._lock:
                self._frame = None
                if not self._error:
                    self._state = 'Остановлено; ресурсы WGC освобождены'
