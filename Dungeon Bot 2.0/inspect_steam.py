"""Read one fresh native WGC frame for development, with no mouse/keyboard input."""
import time
from pathlib import Path
import winmouse as win
win.enable_dpi()
from PySide6.QtWidgets import QApplication
from targets import steam_windows
from gamearea import GameArea
from livecapture import LiveCapture
app = QApplication([])
_, windows = steam_windows()
if not windows:
    raise RuntimeError('Steam window not found')
target = windows[0]
area = GameArea.create(target['hwnd'], (0,0,target['width'],target['height']))
capture = LiveCapture(target['hwnd'],area)
capture.start()
try:
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        frame=capture.latest_frame()
        if frame:
            frame.image.save(str(Path(__file__).with_name('steam-current.png')))
            print(target)
            break
        if capture.snapshot()['error']:
            raise RuntimeError(capture.snapshot()['error'])
        time.sleep(.1)
    else:
        raise RuntimeError('No fresh frame')
finally:
    capture.request_stop()
    capture.wait(5000)
