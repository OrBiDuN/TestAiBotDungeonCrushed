"""Finite, user-started five-click route. No retries of sent actions."""
import json
import time
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtGui import QImage
import winmouse as win
from windowwake import WindowWake

ROOT = Path(__file__).parent
STEPS = ('home', 'ranking', 'track', 'card', 'normal')
LABELS = dict(home='Осады на главном экране', ranking='Осады в рейтинге',
              track='Выследить босса', card='Атаковать в карточке', normal='Обычная Атака', all='На все')


def pixels(image):
    image = image.convertToFormat(QImage.Format_RGBA8888)
    data = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())
    return cv2.cvtColor(data[:, :image.width()*4].reshape(image.height(), image.width(), 4), cv2.COLOR_RGBA2BGR)


class ButtonMatcher:
    def __init__(self):
        self.templates = {name: cv2.imdecode(np.fromfile(ROOT/'assets'/'siege'/f'{name}.png', np.uint8),
                                            cv2.IMREAD_COLOR) for name in (*STEPS, 'all', 'battle_close', 'battle_turn', 'boss_done', 'boss_back')}

    def find(self, image, name):
        h, w = image.shape[:2]
        # Initial verified layout family: supplied full-client ~1920x1080 captures.
        if not (1850 <= w <= 1950 and 1020 <= h <= 1120):
            raise RuntimeError(f'Для маршрута нужны кадры около 1920×1080; сейчас {w}×{h}. '
                               'Масштабировать координаты вслепую запрещено.')
        if name == 'battle_close':
            x0, y0, x1, y1 = w-110, 0, w, 120
        elif name == 'battle_turn':
            x0, y0, x1, y1 = 0, 0, 220, 110
        elif name == 'home':
            x0, y0, x1, y1 = 630, 560, 780, min(h, 820)
        else:
            x0, y0, x1, y1 = 680, 200 if name in ('track', 'card') else 750, min(w, 1240), min(h, 1050)
        roi = image[y0:y1, x0:x1]
        base = self.templates[name]
        candidates = []
        for scale in (1.0, .98, 1.02):
            template = cv2.resize(base, None, fx=scale, fy=scale)
            th, tw = template.shape[:2]
            result = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
            # Suppress nearby duplicate hits; only actual red/orange button likeness accepted.
            for _ in range(4):
                _, score, _, (x, y) = cv2.minMaxLoc(result)
                if score < .91:
                    break
                patch = roi[y:y+th, x:x+tw]
                error = float(np.mean(np.abs(patch.astype(np.float32)-template)))
                if error < 24:
                    candidates.append(dict(point=(x0+x+tw//2, y0+y+th//2), rect=(x0+x, y0+y, tw, th), score=score, error=error))
                result[max(0,y-th//2):y+th//2+1, max(0,x-tw//2):x+tw//2+1] = -1
        if not candidates:
            return None
        # The uppermost visible ordinary boss, never the clan search.
        return min(candidates, key=lambda c: c['point'][1]) if name == 'card' else max(candidates, key=lambda c:c['score'])


class SiegeRoute:
    def __init__(self, launcher):
        self.ui = launcher
        self.matcher = ButtonMatcher()
        self.active = False
        self.timer = QTimer(launcher)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.tick)
        self.attempts = set()
        self.phase = 'idle'
        self.run_id = None

    def log(self, event, **fields):
        entry = dict(at=datetime.now().isoformat(), run=self.run_id, event=event, **fields)
        with (ROOT/'siege-actions.jsonl').open('a', encoding='utf-8') as out:
            out.write(json.dumps(entry, ensure_ascii=False)+'\n')
        self.ui.report(event)

    def frame(self):
        ui = self.ui
        if ui.bound != self.hwnd or not ui.area or ui.area != self.area or ui.live is not self.live:
            raise RuntimeError('Окно, калибровка или сеанс захвата изменились.')
        self.area.rectangle()
        frame = ui.latest_video_frame()
        if not frame or time.perf_counter()-frame.received > .5:
            raise RuntimeError('Нет свежего кадра WGC (не старше 0,5 с).')
        if self.live.area != self.area:
            raise RuntimeError('Кадр и калибровка не соответствуют друг другу.')
        return frame

    def start(self, navigation_only=False):
        if self.active:
            # A duplicate UI event must not reach guard(), which cancels on errors.
            self.ui.report('Маршрут уже выполняется; повторный запуск пропущен.')
            return
        ui = self.ui
        if not ui.bound or not ui.area or not ui.live or not ui.live.isRunning():
            raise RuntimeError('Выберите Steam-окно, клиентскую область и включите трансляцию.')
        import psutil
        if psutil.Process(win.identity(ui.bound)[1]).name().casefold() != 'dungeoncrusher.exe':
            raise RuntimeError('Маршрут предназначен только для dungeoncrusher.exe.')
        self.hwnd, self.area, self.live = ui.bound, ui.area, ui.live
        if self.area.crop[:2] != (0, 0) or self.area.crop[2:] != self.area.size:
            raise RuntimeError('Для маршрута выберите всю клиентскую область.')
        ui.cancel()
        self.run_id = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.attempts = set()
        self.index = 0
        self.limit = 2 if navigation_only else 5
        self.phase = 'wake'
        self.resume_phase = 'find'
        self.wake = WindowWake(self.hwnd)
        self.deadline = time.monotonic()+8
        self.active = True
        self.ui.set_route_running(True)
        self.timer.start()
        self.log('Маршрут начат: только навигация.' if navigation_only else
                 'Маршрут начат: один поиск и одна обычная атака разрешены нажатием кнопки.')

    def cancel(self, reason='Маршрут остановлен.'):
        was_active = self.active
        self.active = False
        self.ui.set_route_running(False)
        self.timer.stop()
        if was_active:
            self.log(reason, attempts=sorted(self.attempts))

    def pre_click(self, key, expected):
        frame = self.frame()
        match = self.matcher.find(pixels(frame.image), key)
        if not match or max(abs(a-b) for a,b in zip(match['point'], expected)) > 6:
            raise RuntimeError('Кнопка исчезла или сместилась перед кликом. Действие отменено.')
        if key in self.attempts:
            raise RuntimeError('Повтор уже отправленной команды запрещён.')
        # Persist BEFORE SendInput, including cases with uncertain injection outcome.
        self.attempts.add(key)
        self.log(f'Одна попытка: {LABELS[key]}', action=key, point=expected, score=match['score'])

    def tick(self):
        if not self.active:
            return
        try:
            ui = self.ui
            if win.user32.GetAsyncKeyState(0x1B) & 0x8000:
                ui.stop()
                return
            now = time.monotonic()
            if self.phase not in ('click', 'wake') and win.user32.GetForegroundWindow() != self.hwnd:
                self.resume_phase = self.phase
                self.phase = 'wake'
                self.wake = WindowWake(self.hwnd)
            if self.phase == 'wake':
                if not self.wake.poll():
                    return
                frame = ui.latest_video_frame()
                if not frame or frame.received < self.wake.ready_at or time.perf_counter()-frame.received > .5:
                    if time.perf_counter()-self.wake.started > 8:
                        raise RuntimeError('Окно активно, но новый кадр WGC после пробуждения не поступил.')
                    return
                self.phase = self.resume_phase
                self.deadline = now+10
                self.log('Окно пробуждено; получен свежий кадр WGC.')
            if self.phase == 'click':
                if ui.operation is not None:
                    return
                self.phase = 'settle'
                self.ready = now+1.0
                self.deadline = now+10
                self.after_sequence = self.frame().sequence
                return
            if self.phase == 'settle':
                if now < self.ready:
                    return
                frame = self.frame()
                if frame.sequence <= self.after_sequence:
                    return
                if self.index+1 >= self.limit:
                    if self.limit == 2 and not any(self.matcher.find(pixels(frame.image), k) for k in ('track','card')):
                        if now > self.deadline:
                            raise RuntimeError('Список осад не подтверждён после навигации.')
                        return
                    # Keep evidence, not a fabricated combat result or damage attribution.
                    path = ROOT/'screenshots'/f'siege-{self.run_id}-after.png'
                    path.parent.mkdir(exist_ok=True)
                    frame.image.save(str(path))
                    self.cancel('Навигация завершена.' if self.limit == 2 else
                                'Одна обычная атака отправлена. Контрольный кадр сохранён; исход боя требует проверки. Повтора нет.')
                    return
                next_key = STEPS[self.index+1]
                if not self.matcher.find(pixels(frame.image), next_key):
                    if now > self.deadline:
                        raise RuntimeError('Следующий экран не подтверждён. Исход неизвестен; повтор команды не выполняется.')
                    return
                self.index += 1
                self.phase = 'find'
            key = STEPS[self.index]
            frame = self.frame()
            match = self.matcher.find(pixels(frame.image), key)
            if not match:
                if now > self.deadline:
                    raise RuntimeError(f'Не найдена кнопка «{LABELS[key]}». Ничего не нажато повторно.')
                return
            self.ui.relative_point = match['point']
            self.ui.point = self.area.absolute(match['point'])
            self.ui.begin(True, from_route=True)
            self.ui.operation['check_before_click'] = lambda: self.pre_click(key, match['point'])
            self.phase = 'click'
        except Exception as exc:
            self.cancel(f'Маршрут прерван: {exc}')
            self.ui.cancel()
