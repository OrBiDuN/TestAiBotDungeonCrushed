"""Owned animated test window. No injected input, no browser interaction."""
import time
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QWidget


class DemoWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Dungeon Bot — тест видеопотока')
        self.resize(640, 400)
        self.counter = 0
        self.clock = QTimer(self)
        self.clock.timeout.connect(self.animate)
        self.clock.start(33)

    def animate(self):
        self.counter += 1
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('#142335'))
        p.fillRect((self.counter*7) % max(1, self.width()-90), 140, 90, 90,
                   QColor.fromHsv(self.counter % 360, 220, 240))
        p.setPen(Qt.white)
        f = p.font()
        f.setPointSize(20)
        p.setFont(f)
        p.drawText(24, 55, 'Живой тест Windows Graphics Capture')
        p.drawText(24, 100, f'Анимация: {self.counter}')
        p.drawText(24, self.height()-35, time.strftime('%H:%M:%S'))
