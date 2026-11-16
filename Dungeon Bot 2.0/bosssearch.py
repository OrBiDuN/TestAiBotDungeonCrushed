"""Latest-only passive vision and a finite, explicitly started boss search."""
import time
from human_input import scroll_interval
from PySide6.QtCore import QThread
from siege import ButtonMatcher, SiegeRoute, pixels
import winmouse as win
from cardvision import CardDetector
import ctypes as C


def scroll_step(direction):
    event = win.INPUT(type=0, mi=win.MOUSEINPUT(0, 0, (120*direction) & 0xffffffff, 0x0800, 0, win.TAG))
    if win.user32.SendInput(1, C.byref(event), C.sizeof(win.INPUT)) != 1:
        raise RuntimeError('Windows отклонила прокрутку списка.')


class SceneDetector:
    def __init__(self):
        self.matcher = ButtonMatcher()
        self.cards = CardDetector()

    def inspect(self, image):
        if self.matcher.battle_ready(image):
            return {'scene': 'Бой — крестик найден', 'track': None}
        if self.matcher.find(image, 'boss_done'):
            return {'scene': 'Осада босса завершена', 'track': None}
        cards = self.cards.detect(image)
        track = self.matcher.find(image, 'track')
        if track:
            return {'scene': 'Осады — поиск боссов', 'track': track, 'cards': cards}
        if cards:
            return {'scene': 'Осады — список боссов', 'track': None, 'cards': cards}
        for key, label in [('normal', 'Меню босса'), ('card', 'Осады — список боссов'),
                           ('ranking', 'Рейтинг осады'), ('home', 'Главный экран')]:
            if self.matcher.find(image, key):
                if key == 'normal':
                    label += ' · Атака найдена'
                    if self.matcher.find(image, 'all'):
                        label += ' · На все найдена'
                return {'scene': label, 'track': None}
        return {'scene': 'Экран не распознан', 'track': None}


class VisionWorker(QThread):
    """One frame under analysis and one result; no queued frame signals."""
    def __init__(self, capture, parent=None):
        super().__init__(parent)
        self.capture = capture
        self.result = None
        self.ocr_result = None
        self.relogin_result = None
        import uuid
        self.session = uuid.uuid4().hex
        self.store = getattr(parent,'boss_store',None)
        self.scope = str(getattr(parent,'bound','unbound'))
        self.route_id = self.session

    def run(self):
        detector = SceneDetector()
        sequence = -1
        reader = None
        next_ocr = 0
        while not self.isInterruptionRequested():
            frame = self.capture.latest_frame()
            if frame and frame.sequence != sequence:
                sequence = frame.sequence
                try:
                    result = detector.inspect(pixels(frame.image))
                except Exception as exc:
                    result = {'scene': str(exc), 'track': None}
                self.result = dict(result, received=frame.received, sequence=sequence)
                if time.monotonic() >= next_ocr:
                    next_ocr = time.monotonic()+1
                    try:
                        from relogin import detect
                        match = detect(pixels(frame.image))
                        self.relogin_result = dict(match=match, received=frame.received, sequence=sequence, error=None)
                    except Exception as exc:
                        self.relogin_result = dict(match=None, received=frame.received, sequence=sequence, error=str(exc))
                    try:
                        if reader is None:
                            from bossocr import BossReader
                            reader = BossReader(self.store)
                        token=f'{self.session}:{sequence}'
                        rows = reader.read(pixels(frame.image), result.get('cards', []),token,frame.wall_time)
                        if self.store:
                            rows=self.store.observe_instances(rows,self.scope,self.route_id,token,frame.wall_time)
                        no_attacks=False
                        if not rows and result['scene']=='Экран не распознан':
                            import asyncio
                            image=pixels(frame.image)
                            if image.shape[1]>=1240:
                                message=asyncio.run(reader.text(image[780:950,700:1220])).lower()
                                no_attacks=any(s in message for s in ('нет доступных атак','недостаточно атак','атаки закончились'))
                        self.ocr_result = dict(rows=rows, received=frame.received, sequence=sequence, error=None,no_attacks=no_attacks)
                    except Exception as exc:
                        self.ocr_result = dict(rows=[], received=frame.received, sequence=sequence, error=str(exc))
            self.msleep(150)


class BossSearch(SiegeRoute):
    def recover_error(self, exc):
        if self.active and getattr(self,'combat',None) is not None:
            self.combat.recover(exc)
            return True
        return False

    """Find again after every click. Never attack or search for a clan boss."""
    def start(self, navigation_only=False, open_boss=False, attack_once=False, kill_boss=False, endless=False):
        super().start(True)
        if getattr(self, 'search_started', False):
            return
        self.search_started = True
        self.sent = 0
        self.previous_point = None
        self.sent_sequence = -1
        self.missing_since = None
        self.last_sequence = -1
        self.card_detector = CardDetector()
        self.known_count = 0
        self.scrolls = 0
        self.open_boss = open_boss
        self.attack_once = attack_once
        self.kill_boss = kill_boss
        self.endless = endless
        self.completed_bosses = 0
        self.total_attacks = 0
        self.combat = None
        if getattr(self.ui,'vision',None) and hasattr(self.ui.vision,'route_id'):
            self.ui.vision.route_id = self.run_id
        self.timer.setInterval(100)
        self.log('Бесконечный режим: один поиск → добивание → Назад → следующий поиск.' if endless else
                 'Поиск: заново определяю кнопку после каждого клика, максимум 4 поиска.')

    def cancel(self, reason='Поиск остановлен.'):
        super().cancel(reason)
        self.search_started = False

    def finish_search(self, reason):
        if not getattr(self, 'open_boss', False):
            self.cancel(reason)
            return
        if getattr(self, 'endless', False):
            # One fresh card only: never scroll through or select an older siege.
            self.log(reason + ' Читаю единственную найденную карточку.')
            self.phase = 'read_boss'
            self.ready = time.monotonic() + .6
            self.read_min_time = time.perf_counter() + .6
            self.read_deadline = time.monotonic() + 10
            self.read_signature = None
            return
        self.log(reason + ' Возвращаю список вверх перед выбором первого босса.')
        self.start_scroll(1, 'read_boss')

    def on_combat_finished(self):
        """A result and Back were observed; only a newly seen Track button starts another boss."""
        self.completed_bosses = getattr(self, 'completed_bosses', 0) + 1
        self.combat = None
        self.sent = self.known_count = 0
        self.previous_point = None
        self.sent_sequence = self.last_sequence = -1
        self.missing_since = None
        self.selected_instance = self.selected_portrait = None
        if not getattr(self, 'endless', False):
            self.cancel('Осада завершена; возврат в список боссов подтверждён.')
            return
        self.phase = 'wait_next_track'
        self.next_track_deadline = time.monotonic() + 12
        self.log(f'Босс #{self.completed_bosses} завершён. Ожидаю «Выследить босса» для следующего цикла.')

    def start_scroll(self, direction, after):
        cards = self.card_detector.detect(pixels(self.frame().image))
        if not cards:
            raise RuntimeError('Не вижу список боссов для прокрутки.')
        x,y,w,h = cards[len(cards)//2]['rect']
        self.ui.relative_point = (x+w//2,y+h//2)
        self.ui.point = self.area.absolute(self.ui.relative_point)
        self.ui.begin(False, from_route=True, fast=True)
        self.scroll_direction, self.after_scroll = direction, after
        self.scroll_remaining = 100
        self.phase = 'scroll_move'

    def verify_boss_click(self, row):
        from bossocr import fingerprint
        frame = self.frame()
        image = pixels(frame.image)
        cards = self.card_detector.detect(image)
        card = next((c for c in cards if c.get('attack') == row['attack'] and not c['partial']), None)
        if not card or fingerprint(image, card['anchor']) != row['fingerprint']:
            raise RuntimeError('Карточка изменилась перед нажатием «Атаковать».')
        self.log('Открываю карточку босса: '+row['name'], points=row['points'])
        self.selected_instance = row.get('instance_id')
        # Card portrait becomes an identity guard in the following boss menu.
        x,y=card['anchor']
        self.selected_portrait = image[y-150:y-55,x-350:x-260].copy()
        self.save_endless_frame(frame, 'found')

    def verify_search_click(self, expected):
        frame = self.frame()
        visible = len(self.card_detector.detect(pixels(frame.image)))
        self.known_count = max(self.known_count, visible)
        if self.known_count >= 4:
            raise RuntimeError('Достигнут лимит 4 боссов; поиск не отправлен.')
        match = self.matcher.find(pixels(frame.image), 'track')
        if not match or max(abs(a-b) for a,b in zip(match['point'], expected)) > 6:
            raise RuntimeError('Кнопка поиска сместилась перед кликом; поиск остановлен.')
        self.sent += 1
        # Conservative reservation: even an uncertain click must not exceed capacity.
        self.known_count += 1
        self.previous_point = expected
        self.sent_sequence = frame.sequence
        self.log('Нажатие «Выследить босса».', number=self.sent, point=expected)

    def tick(self):
        if not self.active:
            return
        try:
            ui = self.ui
            if win.user32.GetAsyncKeyState(0x1B) & 0x8000:
                ui.stop()
                return
            now = time.monotonic()
            if self.wait_for_video():
                return
            if getattr(self, 'combat', None) is not None:
                self.combat.tick()
                return
            if getattr(self,'endless',False) and ui.operation is None and self.phase!='wake':
                frame=self.frame()
                if self.matcher.find(pixels(frame.image),'attack_failed_ok'):
                    from bosscombat import CombatCycle
                    self.combat=CombatCycle(self)
                    self.combat.tick()
                    return
            if self.phase == 'wait_next_track':
                frame = self.frame()
                if self.matcher.find(pixels(frame.image), 'track'):
                    self.phase = 'find'
                    self.ready = now + .2
                    self.log('Следующий поиск доступен; начинаю новый цикл.')
                elif now > self.next_track_deadline:
                    self.cancel('После завершения не появилась «Выследить босса». Следующий поиск не отправлен.')
                return
            if self.phase in ('scroll_move', 'scroll_burst'):
                if ui.operation is not None:
                    return
                self.frame()  # Do not keep scrolling after capture has stalled.
                ui.validate_target()
                if win.position() != ui.point:
                    raise RuntimeError('Курсор сдвинут; прокрутка отменена.')
                self.phase = 'scroll_burst'
                self.timer.setInterval(scroll_interval())
                scroll_step(self.scroll_direction)
                self.scroll_remaining -= 1
                if self.scroll_remaining == 0:
                    self.timer.setInterval(100)
                    self.scrolls += self.scroll_direction < 0
                    self.previous_point = None
                    self.sent_sequence = self.frame().sequence
                    self.ready = now+.8
                    self.read_min_time = time.perf_counter()+.8
                    self.missing_since = None
                    self.phase = self.after_scroll
                    self.read_deadline = now+10
                    self.read_signature = None
                    self.log('Отправлено 100 отдельных делений '+('вверх' if self.scroll_direction > 0 else 'вниз')+'; жду новый кадр.')
                return
            if self.phase == 'boss_click':
                if ui.operation is None:
                    self.phase = 'confirm_boss'
                    self.confirm_deadline = now+5
                return
            if self.phase == 'confirm_boss':
                frame = self.frame()
                match = self.matcher.find(pixels(frame.image), 'normal')
                if getattr(self, 'kill_boss', False) and (match or self.matcher.find(pixels(frame.image), 'boss_done')):
                    from bosscombat import CombatCycle
                    self.combat = CombatCycle(self)
                    self.log('Начат цикл добивания первого босса.')
                    return
                if match:
                    if getattr(self, 'attack_once', False):
                        point = match['point']
                        ui.relative_point = point
                        ui.point = self.area.absolute(point)
                        ui.begin(True, from_route=True, fast=True)
                        ui.operation['check_before_click'] = lambda: self.pre_click('normal', point)
                        self.phase = 'ordinary_attack'
                        self.attack_sequence = frame.sequence
                    else:
                        self.cancel('Меню босса открыто. Нажатие «Атаковать» подтверждено.')
                elif now > self.confirm_deadline:
                    self.cancel('Нажатие отправлено, меню босса не подтверждено; повтор не выполняется.')
                return
            if self.phase == 'ordinary_attack':
                if ui.operation is None:
                    self.phase = 'confirm_attack'
                    self.confirm_deadline = now+5
                return
            if self.phase == 'confirm_attack':
                frame = self.frame()
                if frame.sequence > self.attack_sequence and not self.matcher.find(pixels(frame.image), 'normal'):
                    self.cancel('Обычная атака отправлена один раз; экран меню изменился. Исход боя не определён.')
                elif now > self.confirm_deadline:
                    self.cancel('Обычная атака отправлена; переход не подтверждён. Повтор исключён.')
                return
            if self.phase == 'read_boss':
                if now > self.read_deadline:
                    raise RuntimeError('Первая карточка не подтверждена на устойчивом кадре; «Атаковать» не нажата.')
                if now < self.ready:
                    return
                frame = self.frame()
                if frame.received < self.read_min_time or frame.sequence <= self.sent_sequence:
                    return
                image = pixels(frame.image)
                cards = self.card_detector.detect(image)
                if not cards or cards[0]['partial'] or not 380 <= cards[0]['attack'][1] <= 450:
                    self.read_signature = None
                    return
                from bossocr import fingerprint
                card = cards[0]
                signature = (card['attack'], fingerprint(image, card['anchor']))
                if self.read_signature != signature:
                    self.read_signature = signature
                    self.read_sequence = frame.sequence
                    self.card_stable_since = now
                    return
                if frame.sequence <= self.read_sequence or now-self.card_stable_since < .3:
                    return
                row = dict(attack=card['attack'], fingerprint=signature[1], name='первая карточка', points=None)
                result = ui.vision.ocr_result if ui.vision else None
                if result and not result['error'] and time.perf_counter()-result['received'] < 1.5:
                    for candidate in result['rows']:
                        if candidate.get('attack') == row['attack'] and candidate.get('fingerprint') == row['fingerprint']:
                            row['name'] = candidate.get('name') or row['name']
                            row['points'] = candidate.get('points')
                            row['instance_id'] = candidate.get('instance_id')
                            break
                self.log('Первая карточка подтверждена изображением; OCR используется только для журнала.')
                ui.relative_point = row['attack']
                ui.point = self.area.absolute(row['attack'])
                ui.begin(True, from_route=True, fast=True)
                ui.operation['check_before_click'] = lambda: self.verify_boss_click(row)
                self.phase = 'boss_click'
                return
            if self.phase == 'wake':
                if not self.wake.poll():
                    return
                frame = ui.latest_video_frame()
                if not frame or frame.received < self.wake.ready_at or time.perf_counter()-frame.received > .5:
                    if time.perf_counter()-self.wake.started > 8:
                        raise RuntimeError('После пробуждения нет свежего кадра.')
                    return
                self.phase = 'find'
                self.deadline = now+4
            if self.phase == 'click':
                if ui.operation is not None:
                    return
                self.phase = 'find'
                self.deadline = now+4
                self.ready = now+.25
                return
            if win.user32.GetForegroundWindow() != self.hwnd:
                from windowwake import WindowWake
                self.wake = WindowWake(self.hwnd)
                self.phase = 'wake'
                return
            if now < getattr(self, 'ready', 0):
                return
            frame = self.frame()
            if frame.sequence == self.last_sequence or frame.sequence <= self.sent_sequence:
                return
            self.last_sequence = frame.sequence
            cards = self.card_detector.detect(pixels(frame.image))
            self.known_count = max(self.known_count, len(cards))
            if self.known_count >= (1 if getattr(self, 'endless', False) else 4):
                self.finish_search('Найдена одна осада; прекращаю поиск.' if getattr(self, 'endless', False) else
                                   'Лимит: 4 босса одновременно. Поиск завершён.')
                return
            match = self.matcher.find(pixels(frame.image), 'track')
            if not match:
                self.missing_since = self.missing_since or now
                if now-self.missing_since >= .6:
                    if len(cards) == 3 and self.scrolls < 2:
                        self.start_scroll(-1, 'find')
                        return
                    self.finish_search('Кнопка «Выследить босса» больше не видна; поиск остановлен.' if self.sent else
                                'Кнопка не найдена. Откройте окно «Осады» и запустите поиск.')
                return
            self.missing_since = None
            if self.sent >= (1 if getattr(self, 'endless', False) else 4):
                self.finish_search('Выполнен один поиск; перехожу к найденной карточке.' if getattr(self, 'endless', False) else
                                   'Выполнено 4 поиска; достигнут предел одного запуска.')
                return
            point = match['point']
            if self.previous_point and max(abs(a-b) for a,b in zip(point, self.previous_point)) < 10:
                if now > self.deadline:
                    raise RuntimeError('После клика кнопка не переместилась. Повтор в старую точку отменён.')
                return
            ui.relative_point = point
            ui.point = self.area.absolute(point)
            ui.begin(True, from_route=True, fast=True)
            ui.operation['check_before_click'] = lambda: self.verify_search_click(point)
            self.phase = 'click'
        except Exception as exc:
            if self.recover_error(exc):return
            self.cancel(f'Поиск прерван: {exc}')
            self.ui.cancel()


