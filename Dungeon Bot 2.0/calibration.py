"""Select a game rectangle on a static screenshot; no clicks reach the game."""
from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QPixmap, QPainter, QPen
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox


class Selection(QLabel):
    changed = Signal()

    def __init__(self, image, parent):
        super().__init__(parent)
        self.source = image
        self.start = self.end = None
        screen = parent.screen().availableGeometry()
        pix = QPixmap.fromImage(image).scaled(int(screen.width()*.8), int(screen.height()*.65),
                                             Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(pix)
        self.setFixedSize(pix.size())
        self.setCursor(Qt.CrossCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start = self.end = event.position().toPoint()
            self.update()

    def mouseMoveEvent(self, event):
        if self.start is not None and event.buttons() & Qt.LeftButton:
            self.end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.start is not None:
            self.end = event.position().toPoint()
            self.update()
            self.changed.emit()

    def crop(self):
        if self.start is None:
            return (0, 0, 0, 0)
        x1, x2 = sorted((self.start.x(), self.end.x()))
        y1, y2 = sorted((self.start.y(), self.end.y()))
        sx, sy = self.source.width()/self.width(), self.source.height()/self.height()
        x1, x2 = [round(max(0, min(self.width(), x))*sx) for x in (x1, x2)]
        y1, y2 = [round(max(0, min(self.height(), y))*sy) for y in (y1, y2)]
        return x1, y1, x2-x1, y2-y1

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.start is not None:
            painter = QPainter(self)
            painter.setPen(QPen(Qt.green, 2))
            painter.drawRect(QRect(self.start, self.end).normalized())


class CalibrationDialog(QDialog):
    def __init__(self, image, parent):
        super().__init__(parent)
        self.setWindowTitle('Выделите игровую область на снимке')
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Протяните рамку от верхнего левого до нижнего правого угла игры.\n'
                                'Это статичный снимок: клики в игру не передаются.'))
        self.selection = Selection(image, self)
        layout.addWidget(self.selection)
        self.size_label = QLabel('Область ещё не выбрана')
        layout.addWidget(self.size_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.save = buttons.button(QDialogButtonBox.Save)
        self.save.setText('Сохранить область')
        self.save.setEnabled(False)
        buttons.button(QDialogButtonBox.Cancel).setText('Отмена')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.selection.changed.connect(self.update_selection)
        layout.addWidget(buttons)

    def update_selection(self):
        x, y, w, h = self.selection.crop()
        self.size_label.setText(f'X={x}, Y={y}, размер {w}×{h} физических пикселей')
        self.save.setEnabled(w >= 10 and h >= 10)
