"""One user-selected session owns preparation, relogin and endless combat."""
import time
from siege import SiegeRoute, pixels


class SiegeNavigation(SiegeRoute):
    def start_navigation(self):
        super().start(True)
        self.destination = None
        self.expires = time.monotonic() + 120
        self.last_sequence = -1
        self.waiting_key = None
        self.click_pending = False
        self.next_status = time.monotonic() + 10

    def tick(self):
        if not self.active:
            return
        try:
            if self.wait_for_video() or self.ui.operation is not None:
                return
            if time.monotonic() > self.expires:
                raise RuntimeError('Не удалось распознать вход в осаду за 120 секунд. См. screenshots/navigation.')
            if self.phase == 'wake':
                if not self.wake.poll():
                    return
                self.phase = 'observe'
            frame = self.frame()
            if self.click_pending:
                self.last_sequence = frame.sequence
                self.click_pending = False
                return
            if frame.sequence <= self.last_sequence or frame.received < self.wake.ready_at:
                return
            self.last_sequence = frame.sequence
            image = pixels(frame.image)
            m = self.matcher
            # The modal takes priority over every control visible behind it.
            popup = m.find(image, 'offline_gold_ok')
            if popup:
                if self.waiting_key != 'offline_gold_ok':
                    self.ui.autopilot.notice('Получено золото за время отсутствия. Нажимаю ОК.')
                    self.ui.relative_point = popup['point']
                    self.ui.point = self.area.absolute(popup['point'])
                    self.ui.begin(True, from_route=True, fast=True)
                    self.ui.operation['check_before_click'] = lambda point=popup['point']: self.pre_click('offline_gold_ok', point)
                    self.waiting_key = 'offline_gold_ok'
                    self.click_pending = True
                    self.last_sequence = frame.sequence
                return
            if m.find(image, 'track') or m.find(image, 'card'):
                self.destination = 'list'
            elif m.find(image, 'normal') or m.find(image, 'boss_done'):
                self.destination = 'menu'
            elif m.battle_ready(image):
                self.destination = 'battle'
            if self.destination:
                self.cancel('Вход в осаду подтверждён.')
                return
            for key, message in [('ranking', 'Открыл осаду. Перехожу к поиску боссов.'),
                                 ('home', 'Сейчас стартовое окно. Открываю осаду.')]:
                hit = m.find(image, key)
                if not hit or self.waiting_key == key:
                    continue
                self.ui.autopilot.notice(message)
                self.ui.relative_point = hit['point']
                self.ui.point = self.area.absolute(hit['point'])
                self.ui.begin(True, from_route=True, fast=True)
                self.ui.operation['check_before_click'] = lambda key=key, point=hit['point']: self.pre_click(key, point)
                self.waiting_key = key
                self.click_pending = True
                self.last_sequence = frame.sequence
                return
            if time.monotonic() >= getattr(self, 'next_status', float('inf')):
                from siege import ROOT
                folder = ROOT/'screenshots'/'navigation'
                folder.mkdir(parents=True, exist_ok=True)
                frame.image.save(str(folder/'latest.png'))
                self.next_status = time.monotonic()+15
                self.ui.autopilot.notice('Свежий экран получен. Ожидаю распознавания кнопки входа в осаду. Кадр: screenshots/navigation/latest.png')
        except Exception as exc:
            self.cancel('Ошибка входа в осаду: ' + str(exc))
            self.ui.cancel()


class Autopilot:
    def __init__(self, ui):
        self.ui = ui
        self.active = False
        self.phase = 'idle'
        self.started = None
        self.stopped = None
        self.completed = 0
        self.attacks = 0
        self.relogins = 0
        self._route = self._combat = None
        self._boss_count = self._attack_count = 0
        self.next_stats = 0
        self.next_probe = 0

    def notice(self, text):
        self.ui.report(text)
        if self.ui.telegram:
            from telegram_control import ACTIVE_MENU
            self.ui.telegram.notify(text, menu=ACTIVE_MENU)

    def start(self):
        if self.active or (self.ui.siege and self.ui.siege.active):
            return
        self.ui.cancel()
        self.active = True
        self.started = time.monotonic()
        self.stopped = None
        self.completed = self.attacks = self.relogins = 0
        self._route = self._combat = None
        self._boss_count = self._attack_count = 0
        self.next_stats = self.started + 600
        self.launch_requested = False
        self.phase = 'discover'
        self.deadline = self.started + 120
        self.next_probe = 0
        self.ui.mode_selection = False
        self.notice('Выбран бесконечный режим. Проверяю игру и подготавливаю запуск.')

    def collect_stats(self):
        route = self.ui.siege
        if route is not self._route:
            self._route, self._boss_count = route, 0
            self._attack_count = 0
        count = getattr(route, 'completed_bosses', 0)
        if isinstance(count, int):
            self.completed += max(0, count - self._boss_count)
            self._boss_count = count
        count = getattr(route, 'total_attacks', 0)
        if isinstance(count, int):
            self.attacks += max(0, count - self._attack_count)
            self._attack_count = count

    def stop(self):
        self.collect_stats()
        if self.active:
            self.stopped = time.monotonic()
        self.active = False
        self.phase = 'idle'

    def statistics(self):
        self.collect_stats()
        elapsed = max(0, int((self.stopped if self.stopped is not None else time.monotonic()) - self.started)) if self.started is not None else 0
        stage = {'idle': 'ожидание запуска', 'discover': 'поиск / запуск игры',
                 'capture': 'подготовка области', 'observe': 'ожидание загрузки',
                 'navigation': 'вход в осаду', 'relogin': 'перезаход',
                 'running': 'поиск и атаки боссов'}.get(self.phase, self.phase)
        return (f'Режим: {"бесконечный" if self.active else "остановлен"}\n'
                f'Этап: {stage}\nВремя: {elapsed//3600:02d}:{elapsed//60%60:02d}:{elapsed%60:02d}\n'
                f'Завершено боссов: {self.completed}\nАтак: {self.attacks}\nПерезаходов: {self.relogins}')

    def tick(self):
        if not self.active:
            return
        try:
            self.advance()
        except Exception as exc:
            self.stop()
            self.ui.cancel()
            self.notice('Автозапуск остановлен: ' + str(exc))

    def advance(self):
        now = time.monotonic()
        ui = self.ui
        self.collect_stats()
        if now >= self.next_stats:
            self.next_stats = now + 600
            if ui.telegram:
                ui.telegram.notify('Статистика за текущий запуск\n' + self.statistics())
        if now < self.next_probe:
            return
        self.next_probe = now + .5
        from targets import steam_windows, launch_game
        processes, windows = steam_windows()
        if self.phase != 'discover' and (not windows or ui.bound not in {w['hwnd'] for w in windows}):
            ui.cancel()
            ui.stop_live()
            self.phase = 'discover'
            self.deadline = now + 120
            self.launch_requested = False
            self.notice('Окно игры пропало. Проверяю запуск и восстанавливаю подключение.')
        if self.phase == 'discover':
            if now > self.deadline:
                raise RuntimeError('Игра не создала доступное окно за 120 секунд.')
            if not processes and not self.launch_requested:
                launch_game()
                self.launch_requested = True
                self.notice('Запустил игру. Ожидаю игровое окно.')
            if not windows:
                return
            if ui.find_steam():
                self.notice('Нашёл игру. Определяю игровую область.')
                self.phase = 'capture'
                self.deadline = now + 45
            return
        if self.phase == 'capture':
            if now > self.deadline:
                raise RuntimeError('Не удалось подготовить окно и видеозахват.')
            if ui.pending_activation:
                return
            if ui.live and ui.live.isRunning():
                if ui.telegram_ready():
                    self.phase = 'observe'
                    self.deadline = now + 120
                    self.notice('Область определена. Получаю экран игры.')
                return
            ui.start_live()
            return
        from relogin import ReloginRoute
        if ui.relogin_required and self.phase != 'relogin':
            ui.cancel()
            ui.start_relogin()
            self.phase = 'relogin'
            self.notice('Обнаружен вход с другого устройства. Перезахожу в игру.')
            return
        if self.phase == 'relogin':
            if ui.siege.active:
                return
            if not getattr(ui.siege, 'succeeded', False):
                raise RuntimeError('Перезаход не подтверждён. ' + ui.status.text())
            self.relogins += 1
            self.phase = 'observe'
            self.deadline = now + 120
            self.notice('Перезашёл. Ожидаю загрузки стартового окна.')
            return
        if self.phase == 'observe':
            if now > self.deadline:
                raise RuntimeError('Нет свежего распознавания экрана после загрузки.')
            if not ui.telegram_ready():
                return
            result = getattr(ui.vision, 'relogin_result', None)
            if (result and not result.get('error') and
                    time.perf_counter() - result['received'] <= 2 and result.get('match')):
                ui.relogin_required = True
                return
            if ui.siege:
                ui.siege.timer.deleteLater()
            ui.siege = SiegeNavigation(ui)
            ui.siege.start_navigation()
            self.phase = 'navigation'
            self.notice('Свежий экран получен. Проверяю окно с золотом и вход в осаду.')
            return
        if self.phase == 'navigation':
            if ui.siege.active:
                return
            destination = getattr(ui.siege, 'destination', None)
            if not destination:
                raise RuntimeError(ui.status.text())
            self.notice('Зашёл в поиск боссов.' if destination == 'list' else 'Открыта осада босса. Продолжаю её.')
            ui.start_endless_bosses()
            if destination in ('menu', 'battle'):
                from bosscombat import CombatCycle
                ui.siege.combat = CombatCycle(ui.siege)
                ui.siege.phase = 'combat'
                if destination == 'battle':
                    ui.siege.combat.phase = 'battle'
                    ui.siege.combat.battle_expected = True
            self.phase = 'running'
            self.notice('Запустил выбранный режим: бесконечный поиск боссов. Статистика — каждые 10 минут.')
            return
        if self.phase == 'running' and not ui.siege.active:
            raise RuntimeError('Игровой маршрут остановился. ' + ui.status.text())
