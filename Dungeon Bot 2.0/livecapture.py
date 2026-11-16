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
from runtime_log import logger


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
        self._recoveries = 0
        self._session_closed = threading.Event()
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
        logger.error('WGC hwnd=%s: %s', self.hwnd, exc)
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

    def clear_session_frame(self):
        with self._lock:
            self._frame = None
            self._times.clear()
            self._last = self._last_publish = 0.0

    def run(self):
        control = capture = None
        failures = 0

        def stop_capture():
            nonlocal control, capture
            # Keep valid callbacks until the native thread has joined. The wrapper
            # raises if a callback is None while a final frame is being delivered.
            if capture is not None:
                capture.frame_handler = lambda frame, internal: internal.stop()
                capture.closed_handler = lambda: None
            if control is not None:
                control.stop()
            control = capture = None

        try:
            from windows_capture import WindowsCapture
            logger.info('WGC start hwnd=%s fps=%s', self.hwnd, self.target_fps)
            while not self._stop.is_set():
                if win.identity(self.hwnd) != self.owner:
                    raise RuntimeError('Выбранное окно закрыто или заменено.')
                if win.user32.IsIconic(self.hwnd):
                    self.clear_session_frame()
                    with self._lock:
                        self._state = 'Пауза: окно свёрнуто. Ожидаю разворачивания.'
                    if self._stop.wait(.1):
                        break
                    continue
                self.validate()  # Invalid geometry/identity is not a transport fault.
                self.clear_session_frame()
                self._session_closed.clear()
                reason = None
                try:
                    capture = WindowsCapture(window_hwnd=self.hwnd, cursor_capture=False)
                    capture.frame_handler = self.receive
                    capture.closed_handler = self._session_closed.set
                    control = capture.start_free_threaded()
                    started = time.perf_counter()
                    healthy_since = None
                    with self._lock:
                        self._state = 'Ожидаю первый кадр WGC…'
                    while not self._stop.wait(.1):
                        if win.identity(self.hwnd) != self.owner:
                            self.fail(RuntimeError('Выбранное окно закрыто или заменено.'))
                            break
                        if win.user32.IsIconic(self.hwnd):
                            break  # Recreate the surface after restore.
                        try:
                            self.validate()
                        except Exception as exc:
                            self.fail(exc)
                            break
                        if control.is_finished():
                            control.wait()
                            raise RuntimeError('Сеанс WGC завершился неожиданно.')
                        if self._session_closed.is_set():
                            raise RuntimeError('WGC сообщил о закрытии поверхности захвата.')
                        snap = self.snapshot()
                        now = time.perf_counter()
                        # Count is lifetime-monotonic for vision consumers; first
                        # frame timeout must instead use this session's timestamp.
                        if not snap['last'] and now-started > 8:
                            raise RuntimeError('Нет первого кадра WGC за 8 секунд.')
                        if snap['last'] and now-snap['last'] > 2:
                            raise RuntimeError('Нет новых кадров WGC более 2 секунд.')
                        if snap['last']:
                            if healthy_since is None:
                                healthy_since = now
                                logger.info('WGC frames resumed hwnd=%s sequence=%s', self.hwnd, snap['count'])
                            if now-healthy_since >= 10:
                                failures = 0
                except Exception as exc:
                    reason = str(exc)
                finally:
                    stop_capture()
                    self.clear_session_frame()
                if self._stop.is_set():
                    break
                if reason is not None:
                    failures += 1
                    self._recoveries += 1
                    delay = min(30, 2 ** min(failures-1, 5))
                    with self._lock:
                        self._state = f'Восстановление WGC через {delay} с: {reason}'
                    logger.warning('WGC retry=%s delay=%ss hwnd=%s: %s',
                                   self._recoveries, delay, self.hwnd, reason)
                    if self._stop.wait(delay):
                        break
        except Exception as exc:
            self.fail(exc)
        finally:
            try:
                stop_capture()
            except Exception as exc:
                logger.exception('WGC cleanup failed: %s', exc)
            with self._lock:
                self._frame = None
                if not self._error:
                    self._state = 'Остановлено; ресурсы WGC освобождены'
            logger.info('WGC stopped hwnd=%s error=%s', self.hwnd, self._error)
