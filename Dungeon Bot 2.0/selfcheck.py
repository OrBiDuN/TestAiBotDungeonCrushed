"""Opt-in real Windows integration check against our own harmless Qt target."""
import json
import time
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QPushButton
import winmouse as win


def run(app, launcher):
    target = QPushButton('Тест SendInput: 0 кликов\nТолько собственное тестовое окно')
    target.setWindowTitle('Dungeon Bot — безопасная проверка')
    target.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    target.resize(360, 180)
    target.show()
    context = dict(clicks=0, phase=0, deadline=time.monotonic()+1, observations=[])
    app._selfcheck_target = target
    launcher.recorder.allow_injected = True  # Only this explicit integration test.
    def clicked():
        context['clicks'] += 1
        target.setText(f"Получено настоящих событий окна: {context['clicks']}")
    target.clicked.connect(clicked)

    def check(condition, label):
        if not condition:
            raise AssertionError(label)
        context['observations'].append(label)

    def tick():
        if time.monotonic() < context['deadline']:
            return
        try:
            phase = context['phase']
            if phase == 0:
                target.activateWindow()
                hwnd = int(target.winId())
                left, top, right, bottom = win.rect(hwnd)
                point = ((left+right)//2, (top+bottom)//2)
                context['point'] = point
                launcher.record()
                win.move(*point)
            elif phase == 1:
                check(win.position() == context['point'], 'SendInput physically moved cursor; GetCursorPos matches')
                check(win.root_at(context['point']) == int(target.winId()), 'Target is our own test window')
                win.send(2)
                win.send(4)
            elif phase == 2:
                check(launcher.point == context['point'], 'Global hook captured one injected test click')
                check(not launcher.recorder.handle, 'One-shot recorder unhooked')
                check(context['clicks'] == 1, 'Original click passed through to target')
                launcher.bound = int(target.winId())
                l, t, r, b = win.client_rect(launcher.bound)
                launcher.set_area((10, 10, r-l-20, b-t-20))
                launcher.point = context['point']
                launcher.relative_point = launcher.area.relative(launcher.point)
                win.move(context['point'][0]-70, context['point'][1])
                launcher.begin(True)
                context['deadline'] = time.monotonic()+3.5
            elif phase == 3:
                check(context['clicks'] == 2, 'Replay produced exactly one additional target click')
                check(not launcher.held and launcher.operation is None, 'Replay released mouse and completed')
                launcher.screenshot()
                check(Path(launcher.last_screenshot).stat().st_size > 100, 'mss screenshot PNG saved')
                launcher.begin(True)
                launcher.stop()
                context['deadline'] = time.monotonic()+2
            elif phase == 4:
                check(context['clicks'] == 2, 'STOP cancelled pending click')
                launcher.record()
                launcher.stop()
                check(not launcher.recorder.handle, 'STOP unhooked active recorder')
                win.send(2)
                launcher.held = True
                launcher.stop()
                check(not launcher.held, 'STOP released program-held button')
                context['deadline'] = time.monotonic()+0.5
            elif phase == 5:
                check(not win.user32.GetAsyncKeyState(1) & 0x8000, 'Windows confirms left button is up')
                context['relative'] = launcher.relative_point
                context['before_move'] = launcher.point
                target.move(target.x()+80, target.y()+40)
            elif phase == 6:
                launcher.begin(True)
                check(launcher.point != context['before_move'], 'Window move recalculated physical target')
                check(launcher.relative_point == context['relative'], 'Game-relative point preserved')
                context['deadline'] = time.monotonic()+3.5
            elif phase == 7:
                check(context['clicks'] == 4, 'Replay after window move reached target exactly once')
                launcher.screenshot()
                check((launcher.preview_image.width(), launcher.preview_image.height()) == launcher.area.crop[2:],
                      'Game crop capture and preview have calibrated physical size')
                target.resize(target.width()+40, target.height())
            elif phase == 8:
                try:
                    launcher.validate_target()
                except RuntimeError as exc:
                    check('Размер' in str(exc), 'Changed client size rejected; recalibration required')
                else:
                    raise AssertionError('Changed geometry not rejected')
                l, t, r, b = win.client_rect(launcher.bound)
                launcher.set_area((10, 10, r-l-20, b-t-20))
                check(launcher.point is None, 'Recalibration invalidates old point')
                launcher.area.dpi += 1
                try:
                    launcher.area.rectangle()
                except RuntimeError as exc:
                    check('DPI' in str(exc), 'Changed DPI metadata rejected (simulated)')
                else:
                    raise AssertionError('DPI mismatch not rejected')
                launcher.area.dpi -= 1
                # Verify selector scale mapping with an actual captured image.
                from calibration import CalibrationDialog
                from PySide6.QtCore import QPoint
                dialog = CalibrationDialog(launcher.preview_image, launcher)
                selection = dialog.selection
                selection.start, selection.end = QPoint(0, 0), QPoint(selection.width(), selection.height())
                check(selection.crop() == (0, 0, launcher.preview_image.width(), launcher.preview_image.height()),
                      'Calibration selector maps scaled preview to source pixels')
                dialog.close()
                # Translation during an already scheduled operation must cancel it.
                launcher.point = launcher.area.absolute((30, 30))
                launcher.relative_point = (30, 30)
                launcher.begin(True)
                target.move(target.x()+25, target.y())
            elif phase == 9:
                check(launcher.operation is None and context['clicks'] == 4,
                      'Window move during operation cancelled pending click')
                target.setWindowTitle('Changed test title')
                try:
                    launcher.area.rectangle()
                except RuntimeError as exc:
                    check('Заголовок' in str(exc), 'Changed window title rejected')
                else:
                    raise AssertionError('Title change not rejected')
                launcher.request_capture(True)
                launcher.stop()
                check(not launcher.capture_timer.isActive(), 'STOP cancels scheduled capture')
            elif phase == 10:
                timer.stop()
                def accept_calibration():
                    dialog = launcher.calibration_dialog
                    if dialog:
                        from PySide6.QtCore import QPoint
                        dialog.selection.start = QPoint(5, 5)
                        dialog.selection.end = QPoint(dialog.selection.width()-5, dialog.selection.height()-5)
                        dialog.update_selection()
                        dialog.grab().save(str(Path(__file__).with_name('calibration-preview.png')))
                        dialog.accept()
                QTimer.singleShot(150, accept_calibration)
                launcher.capture_calibration = True
                launcher.complete_capture()
                check(launcher.area.window_title == 'Changed test title' and launcher.point is None,
                      'Real calibration dialog captured window and saved selected region')
                finish(True)
                return
            context['phase'] += 1
            if context['deadline'] < time.monotonic():
                context['deadline'] = time.monotonic()+0.5
        except Exception as exc:
            context['error'] = str(exc)
            finish(False)

    def finish(success):
        timer.stop()
        launcher.stop()
        context['success'] = success
        context['manual_physical_click_verified'] = False
        context['screenshot'] = launcher.last_screenshot
        launcher.grab().save(str(Path(__file__).with_name('launcher-preview.png')))
        Path(__file__).with_name('selfcheck-result.json').write_text(
            json.dumps(context, ensure_ascii=False, indent=2), encoding='utf-8')
        app.exit(0 if success else 1)

    timer = QTimer(launcher)
    timer.timeout.connect(tick)
    timer.start(50)
