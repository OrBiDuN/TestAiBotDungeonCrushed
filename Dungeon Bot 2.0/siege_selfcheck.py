"""Real WGC + SendInput against an owned replay window, never the game."""
import json
import time
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QImage, QColor
from PySide6.QtWidgets import QWidget
from build_siege_assets import read_reference
from siege import ButtonMatcher, STEPS


def run(app, ui):
    refs = [read_reference(i) for i in range(5)]
    matcher = ButtonMatcher()
    expected = [matcher.find(refs[i], STEPS[i])['point'] for i in range(5)]
    # Some attachments are slightly cropped; pad at bottom/right, no rescaling.
    images = []
    for ref in refs:
        h, w = ref.shape[:2]
        image = QImage(ref.data, w, h, ref.strides[0], QImage.Format_BGR888).copy()
        canvas = QImage(1920, 1080, QImage.Format_RGB32)
        canvas.fill(Qt.black)
        p = QPainter(canvas)
        p.drawImage(0,0,image)
        p.end()
        images.append(canvas)

    class Replay(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle('Dungeon Bot — тест маршрута, НЕ игра')
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            self.setGeometry(1920 if app.primaryScreen().virtualGeometry().width() >= 3840 else 0,0,1920,1080)
            self.stage = 0
            self.clicks = []
            self.counter = 0
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.animate)
            self.timer.start(33)

        def animate(self):
            self.counter += 1
            self.update()

        def paintEvent(self,event):
            p = QPainter(self)
            if self.stage < 5:
                p.drawImage(0,0,images[self.stage])
            else:
                p.fillRect(self.rect(), QColor('#123456'))
                p.setPen(Qt.white)
                p.drawText(500,500,'TEST: one normal attack received')
            p.fillRect(1880,2,30,20,QColor.fromHsv(self.counter%360,255,255))

        def mouseReleaseEvent(self,event):
            point = (round(event.position().x()),round(event.position().y()))
            self.clicks.append(dict(stage=self.stage,point=point))
            if self.stage < 5 and max(abs(a-b) for a,b in zip(point,expected[self.stage])) <= 7:
                self.stage += 1
                self.update()

    target = Replay()
    ui._replay_test = target
    target.show()
    target.raise_()
    target.activateWindow()
    hwnd = int(target.winId())
    ui.windows.addItem('Собственное тестовое окно маршрута',hwnd)
    ui.windows.setCurrentIndex(ui.windows.count()-1)
    ui.use_client_area()
    ui.start_live()
    start = time.monotonic()
    result = dict(real_input_to_owned_window=True)
    timer = QTimer(ui)
    state = {'started':False}

    def finish(error=None):
        timer.stop()
        result.update(success=error is None, error=error, clicks=target.clicks, stage=target.stage)
        Path(__file__).with_name('siege-selfcheck.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        ui.stop()
        target.close()
        ui.close()

    def tick():
        try:
            if time.monotonic()-start > 50:
                raise RuntimeError('Timed out: '+ui.status.text())
            if not state['started']:
                frame=ui.latest_video_frame()
                if frame:
                    # Only the test process-name check is substituted. Native capture/input is real.
                    with patch('psutil.Process') as process:
                        process.return_value.name.return_value = 'dungeoncrusher.exe'
                        ui.get_siege().start(False)
                    state['started']=True
            elif not ui.siege.active:
                if target.stage != 5 or len(target.clicks)!=5:
                    raise RuntimeError('Route did not deliver exactly 5 clicks: '+ui.status.text())
                finish()
        except Exception as exc:
            finish(str(exc))
    timer.timeout.connect(tick)
    timer.start(100)
