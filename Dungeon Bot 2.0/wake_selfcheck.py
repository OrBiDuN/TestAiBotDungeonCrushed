"""Native restore/focus regression. Clicks only this test's own start button."""
import json
from pathlib import Path
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget, QPushButton
from launcher import Launcher
from windowwake import WindowWake
import winmouse as win

app = QApplication([])
ui = Launcher()
target = QWidget()
target.setWindowTitle('Dungeon Bot — проверка пробуждения')
target.setGeometry(500, 220, 350, 120)
target.show()
button = QPushButton('Тест авто-пробуждения')
button.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
button.setGeometry(100, 150, 320, 100)
button.show()
result = {'cases': []}
state = {'round': 0}
timer = QTimer()

def finish(error=None):
    timer.stop()
    result.update(success=error is None, error=error)
    ui.pending_activation = dict(wake=WindowWake(int(target.winId())), action=lambda: None)
    ui.cancel()
    result['stop_cancels_wake'] = ui.pending_activation is None
    Path(__file__).with_name('wake-selfcheck.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    button.close()
    ui.close()
    target.close()
    app.exit(0 if error is None else 1)

def click_start():
    # Native user-input precondition: activation starts from a foreground button.
    # Never click unless the physical point belongs to this test's own window.
    try:
        l,t,r,b = win.client_rect(int(button.winId()))
        point = ((l+r)//2,(t+b)//2)
        if win.root_at(point) != int(button.winId()):
            raise RuntimeError('Test button is obscured; no click sent.')
        win.move(*point)
        win.send(2)
        win.send(4)
    except Exception as exc:
        finish(str(exc))

def prepare():
    try:
        if win.user32.GetForegroundWindow() != int(button.winId()):
            raise RuntimeError('Test start button did not acquire foreground.')
        if state['round'] == 0:
            target.showMinimized()
        state['case'] = {'initially_minimized': bool(win.user32.IsIconic(int(target.winId())))}
        state['wake'] = WindowWake(int(target.winId()))
        timer.start(30)
    except Exception as exc:
        finish(str(exc))

def poll():
    try:
        if state['wake'].poll():
            timer.stop()
            case = state['case']
            case['restored'] = not bool(win.user32.IsIconic(int(target.winId())))
            case['foreground_matches'] = win.user32.GetForegroundWindow() == int(target.winId())
            assert case['restored'] and case['foreground_matches']
            result['cases'].append(case)
            state['round'] += 1
            if state['round'] < 2:
                QTimer.singleShot(300, click_start)
            else:
                finish()
    except Exception as exc:
        finish(str(exc))

button.clicked.connect(prepare)
timer.timeout.connect(poll)
QTimer.singleShot(600, click_start)
QTimer.singleShot(12000, lambda: finish('Test timed out.'))
app.exec()
