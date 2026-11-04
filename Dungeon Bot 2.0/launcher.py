import math
import sys
import time
from datetime import datetime
from pathlib import Path

import winmouse as win

win.enable_dpi()

import mss
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox,
                              QDialog, QFormLayout, QHBoxLayout, QLabel, QMainWindow,
                              QPushButton, QTextEdit, QVBoxLayout, QWidget)
from gamearea import GameArea
from calibration import CalibrationDialog
from livecapture import LiveCapture
from windowwake import WindowWake

BASE = Path(__file__).resolve().parent


class Launcher(QMainWindow):
    captured = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Dungeon Bot 2.0 — Live Capture')
        self.live = None
        self.live_sequence = 0
        self.demo_window = None
        self.steam_targets = {}
        self._closing = False
        self.siege = None
        self.vision = None
        self.last_boss_log = None
        self.last_ocr_sequence = -1
        self.pending_activation = None
        from boss_store import BossStore
        self.boss_store = BossStore(BASE / 'data' / 'bosses.sqlite3')
        self.boss_panel = None
        self.resize(1120, 780)
        self.area = None
        self.relative_point = None
        self.calibration_dialog = None
        self.capture_timer = QTimer(self)
        self.capture_timer.setSingleShot(True)
        self.capture_timer.timeout.connect(lambda: self.guard(self.complete_capture))
        self.bound = None
        self.point = None
        self.point_geometry = None
        self.operation = None
        self.held = False
        self.show_position = False
        self.last_screenshot = None
        self.recorder = win.OneClickRecorder(self.captured.emit)
        self.captured.connect(self.on_recorded, Qt.ConnectionType.QueuedConnection)
        body = QWidget()
        self.setCentralWidget(body)
        columns = QHBoxLayout(body)
        layout = QVBoxLayout()
        columns.addLayout(layout, 3)
        preview_layout = QVBoxLayout()
        columns.addLayout(preview_layout, 2)
        preview_layout.addWidget(QLabel('Видеопоток / предпросмотр снимка'))
        video_row = QHBoxLayout()
        self.live_start = self.button('Начать трансляцию', self.start_live)
        self.live_stop = self.button('Остановить трансляцию', self.stop_live)
        video_row.addWidget(self.live_start)
        video_row.addWidget(self.live_stop)
        preview_layout.addLayout(video_row)
        self.fps_choice = QComboBox()
        self.fps_choice.addItems(['5', '10', '15', '30'])
        self.fps_choice.setCurrentText('15')
        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel('Целевой FPS (для следующего запуска):'))
        fps_row.addWidget(self.fps_choice)
        preview_layout.addLayout(fps_row)
        preview_layout.addWidget(self.button('Тестовое окно с анимацией', self.open_demo))
        self.live_status = QLabel('Захват остановлен')
        self.live_status.setWordWrap(True)
        preview_layout.addWidget(self.live_status)
        self.live_metrics = QLabel('FPS: — · Кадров: 0 · Размер: —')
        self.live_metrics.setWordWrap(True)
        preview_layout.addWidget(self.live_metrics)
        preview_layout.addWidget(self.button('Осады: проверить распознавание без кликов', self.inspect_siege))
        preview_layout.addWidget(self.button('Боссы — каталог и текущие осады', self.open_boss_panel))
        self.route_buttons = [
            self.button('БЕСКОНЕЧНО: 1 босс → добить → следующий', self.start_endless_bosses),
            self.button('Поиск → первый босс → добить → Назад', lambda: self.start_boss_search(kill_boss=True)),
            self.button('Добить босса в открытой карточке → Назад', self.start_boss_kill),
            self.button('Атака — один обычный удар в меню босса', lambda: self.start_boss_attack('normal')),
            self.button('На все — атака на все доступные попытки', lambda: self.start_boss_attack('all')),
            self.button('Найти боссов → прочитать → Атаковать первую карточку', self.start_boss_search),
            self.button('Поиск → первый босс → 1 обычная атака', lambda: self.start_boss_search(True)),
            self.button('Открыть список осад (без поиска и атак)', lambda: self.start_siege(True)),
            self.button('Один проход: найти босса и сделать 1 обычную атаку', lambda: self.start_siege(False)),
        ]
        for button in self.route_buttons:
            preview_layout.addWidget(button)
        self.scene_label = QLabel('Экран: ожидаю трансляцию')
        self.scene_label.setWordWrap(True)
        preview_layout.addWidget(self.scene_label)
        self.preview = QLabel('Снимок пока не сделан')
        self.preview.setMinimumSize(300, 240)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet('background: #202020; color: #dddddd;')
        preview_layout.addWidget(self.preview, 1)
        self.preview_info = QLabel('Снимки выполняются только по запросу.')
        self.preview_info.setWordWrap(True)
        preview_layout.addWidget(self.preview_info)
        self.preview_image = None
        heading = QLabel('Dungeon Bot 2.0 · Окно и игровая область')
        heading.setStyleSheet('font-size: 20px; font-weight: 600;')
        layout.addWidget(heading)
        note = QLabel('Steam / Windows · Live Capture. Ввод запускается только кнопками.\n'
                      'СТОП или удерживание Esc отменяет запись, движение и ожидающий клик.\n'
                      'Esc проверяется без перехвата клавиатуры.')
        layout.addWidget(note)
        row = QHBoxLayout()
        self.windows = QComboBox()
        self.windows.setMinimumWidth(300)
        self.windows.addItem('Без привязки — весь рабочий стол', None)
        self.windows.currentIndexChanged.connect(self.bind_selected)
        row.addWidget(self.windows, 1)
        row.addWidget(self.button('Найти Chrome', self.find_chrome))
        layout.addLayout(row)
        layout.addWidget(self.button('Найти Steam Dungeon Crusher (PID / HWND)', self.find_steam))
        self.bound_label = QLabel('Окно не привязано. Найдите Steam-клиент или выберите тестовое окно.')
        self.bound_label.setWordWrap(True)
        layout.addWidget(self.bound_label)
        layout.addWidget(self.button('Калибровать игровую область', lambda: self.request_capture(True)))
        self.area_label = QLabel('Область не задана. Для Steam используйте клиентскую область; для обрезки — калибровку.')
        self.area_label.setWordWrap(True)
        layout.addWidget(self.area_label)
        layout.addWidget(self.button('Использовать всю клиентскую область', self.use_client_area))
        self.coordinates = QLabel('Координаты мыши: —')
        layout.addWidget(self.coordinates)
        layout.addWidget(self.button('Показать координаты мыши', self.toggle_coordinates))
        self.saved = QLabel('Записанная точка: нет')
        layout.addWidget(self.saved)
        self.record_button = self.button('Записать следующий левый клик', self.record)
        self.move_button = self.button('Переместить курсор к записанной точке', lambda: self.begin(False))
        self.click_button = self.button('Повторить записанный клик', lambda: self.begin(True))
        for button in (self.record_button, self.move_button, self.click_button):
            layout.addWidget(button)
        form = QFormLayout()
        self.speed = QDoubleSpinBox()
        self.speed.setRange(50, 5000)
        self.speed.setValue(600)
        self.speed.setSuffix(' пикс/с')
        form.addRow('Скорость движения:', self.speed)
        self.pause = QDoubleSpinBox()
        self.pause.setRange(0.3, 5)
        self.pause.setValue(0.8)
        self.pause.setSuffix(' с')
        form.addRow('Пауза перед кликом:', self.pause)
        layout.addLayout(form)
        layout.addWidget(self.button('Сделать скриншот', self.request_capture))
        stop = self.button('СТОП', self.stop)
        stop.setStyleSheet('background: #b42332; color: white; font-size: 20px; font-weight: bold; padding: 9px;')
        layout.addWidget(stop)
        self.status = QLabel('Готов к ручной проверке.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.document().setMaximumBlockCount(1000)
        layout.addWidget(self.log, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)
        self.video_timer = QTimer(self)
        self.video_timer.timeout.connect(self.poll_live)
        self.video_timer.start(16)

    def open_boss_panel(self):
        if self.boss_panel is None:
            from boss_panel import BossPanel
            self.boss_panel = BossPanel(self.boss_store,self)
        self.boss_panel.refresh()
        self.boss_panel.show()
        self.boss_panel.raise_()

    def open_demo(self):
        from live_demo import DemoWindow
        if self.demo_window is None:
            self.demo_window = DemoWindow()
        self.demo_window.show()
        hwnd = int(self.demo_window.winId())
        index = self.windows.findData(hwnd)
        if index < 0:
            self.windows.addItem('Тест видеопотока (собственное окно)', hwnd)
            index = self.windows.count()-1
        self.windows.setCurrentIndex(index)

    def get_siege(self):
        if self.siege is None:
            from siege import SiegeRoute
            self.siege = SiegeRoute(self)
        return self.siege

    def start_siege(self, navigation_only):
        if self.siege and self.siege.active:
            self.report('Маршрут уже выполняется; повторный запуск пропущен.')
            return
        if self.siege:
            self.siege.timer.deleteLater()
        self.siege = None
        self.get_siege().start(navigation_only)

    def start_boss_search(self, attack_once=False, kill_boss=False):
        if self.siege and self.siege.active:
            self.report('Маршрут уже выполняется; повторный запуск пропущен.')
            return
        from bosssearch import BossSearch
        if self.siege:
            self.siege.timer.deleteLater()
        self.siege = BossSearch(self)
        self.siege.start(open_boss=True, attack_once=attack_once, kill_boss=kill_boss)

    def start_endless_bosses(self):
        if self.siege and self.siege.active:
            self.report('Маршрут уже выполняется; повторный запуск пропущен.')
            return
        from bosssearch import BossSearch
        if self.siege:
            self.siege.timer.deleteLater()
        self.siege = BossSearch(self)
        self.siege.start(open_boss=True, kill_boss=True, endless=True)

    def start_boss_kill(self):
        if self.siege and self.siege.active:
            self.report('Дождитесь завершения действия или нажмите СТОП.')
            return
        from bosscombat import BossKill
        if self.siege:
            self.siege.timer.deleteLater()
        self.siege = BossKill(self)
        self.siege.start_kill()

    def set_route_running(self, running):
        for button in self.route_buttons:
            button.setEnabled(not running)

    def start_boss_attack(self, key):
        if self.siege and self.siege.active:
            self.report('Дождитесь завершения действия или нажмите СТОП.')
            return
        from bossattack import BossAttack
        if self.siege:
            self.siege.timer.deleteLater()
        self.siege = BossAttack(self)
        self.siege.start_attack(key)

    def inspect_siege(self):
        from siege import pixels, STEPS, LABELS
        frame = self.latest_video_frame()
        if not frame or time.perf_counter()-frame.received > .5:
            raise RuntimeError('Нет свежего кадра WGC.')
        matcher = self.get_siege().matcher
        image = pixels(frame.image)
        found = [(LABELS[key], matcher.find(image, key)) for key in STEPS]
        self.report('Найдены: ' + '; '.join(f'{label}: {hit["point"]}, {hit["score"]:.3f}'
                                         for label, hit in found if hit))

    def start_live(self):
        if self.pending_activation:
            previous = self.pending_activation['action']
            def after_activation():
                previous()
                self.start_live()
            self.pending_activation['action'] = after_activation
            return
        if self.live and self.live.isRunning():
            raise RuntimeError('Дождитесь окончания текущего сеанса захвата.')
        if not self.bound:
            raise RuntimeError('Выберите окно в списке или откройте тестовое окно.')
        # Construct first: a stale HWND must not leave self.live pointing at a
        # deleted Qt object if construction raises during a restart.
        replacement = LiveCapture(self.bound, self.area, int(self.fps_choice.currentText()), self)
        if self.vision:
            self.vision.requestInterruption()
            self.vision.wait()
        previous = self.live
        self.live = replacement
        if previous:
            previous.deleteLater()
        self.live_sequence = 0
        self.preview_image = None
        self.preview.clear()
        self.live_start.setEnabled(False)
        self.live_status.setText('Запуск WGC по HWND…')
        self.live.start()
        from bosssearch import VisionWorker
        if self.vision:
            self.vision.deleteLater()
        self.vision = VisionWorker(self.live, self)
        self.last_boss_log = None
        self.last_ocr_sequence = -1
        self.vision.start()
        self.report('Запущен WGC: ' + ('калиброванная область.' if self.area else 'всё окно (калибровка не задана).'))

    def stop_live(self):
        if self.vision:
            self.vision.requestInterruption()
        if self.live and self.live.isRunning():
            self.live.request_stop()
            self.live_status.setText('Остановка WGC…')

    def latest_video_frame(self):
        """Latest-only access for future on-demand vision. No recognition here."""
        return self.live.latest_frame() if self.live else None

    def poll_live(self):
        if not self.live:
            return
        snap = self.live.snapshot()
        ocr = self.vision.ocr_result if self.vision else None
        if ocr and ocr['sequence'] != self.last_ocr_sequence and time.perf_counter()-ocr['received'] < 2:
            self.last_ocr_sequence = ocr['sequence']
            signature = (ocr['error'], tuple((r['order'],r['name'],r['points'],r['partial']) for r in ocr['rows']))
            if signature != self.last_boss_log:
                self.last_boss_log = signature
                stamp = datetime.now().strftime('%H:%M:%S')
                if ocr['error']:
                    self.log.append(f'{stamp}  OCR: {ocr["error"]}')
                elif ocr['rows']:
                    self.log.append(f'{stamp}  Боссы сверху вниз (видимая часть списка):')
                    for row in ocr['rows']:
                        info = 'карточка видна частично' if row['partial'] else (
                            f'{row["name"] or "имя не прочитано"} · очки: {row["points"] if row["points"] is not None else "?"}'
                            + f' · {row.get("points_source", "UNKNOWN")} · осада {row.get("instance_id", "ожидает подтверждения")[:12]}'
                            )
                        self.log.append(f'{stamp}  {row["order"]}. {info}')
        result = self.vision.result if self.vision else None
        fresh = result and time.perf_counter()-result['received'] < .6 and self.live.isRunning()
        self.scene_label.setText('Экран: ' + (result['scene'] if fresh else 'нет свежего кадра'))
        if fresh and result.get('cards'):
            cards = result['cards']
            partial = any(card['partial'] for card in cards)
            self.scene_label.setText(self.scene_label.text() + f' · Видно боссов: {len(cards)}/4'
                                     + (' (одна карточка частично)' if partial else ''))
        frame = self.latest_video_frame()
        if frame and frame.sequence != self.live_sequence:
            self.live_sequence = frame.sequence
            self.preview_image = frame.image
            self.update_preview()
            age = (time.perf_counter()-frame.received)*1000
            self.preview_info.setText(f'Последний кадр: {datetime.fromtimestamp(frame.wall_time):%H:%M:%S.%f}'[:-3]
                                      + f' · доставка в GUI: {age:.1f} мс\n'
                                      + 'WGC по HWND; сохраняются только карточки для базы боссов.')
        stale = snap['last'] and time.perf_counter()-snap['last'] > 2
        actual = snap['fps'] if self.live.isRunning() and not stale else 0
        size = f'{self.preview_image.width()}×{self.preview_image.height()}' if self.preview_image else '—'
        source_age = snap['source_age_ms']
        latency = f'{source_age:.1f} мс' if source_age is not None else 'недоступна'
        self.live_metrics.setText(f'FPS: {actual:.1f} · Кадров: {snap["count"]} · Размер: {size}\n'
                                  f'Копирование: {snap["copy_ms"]:.2f} мс · Возраст кадра WGC: {latency}')
        self.live_status.setText(snap['state'])
        self.live_start.setEnabled(not self.live.isRunning())
        if self._closing and not self.live.isRunning():
            self.close()

    def button(self, text, function):
        button = QPushButton(text)
        button.setMinimumHeight(32)
        button.clicked.connect(lambda _checked=False: self.guard(function))
        return button

    def find_steam(self):
        from targets import steam_windows, STEAM_EXE
        self.cancel()
        processes, windows = steam_windows()
        self.steam_targets = {item['hwnd']: item for item in windows}
        if not windows:
            if processes:
                self.report(f'Процесс найден (PID {list(processes)}), но видимое игровое окно пока отсутствует.')
            else:
                self.report(f'dungeoncrusher.exe не запущен. Запустите Steam-клиент и повторите поиск. Путь: {STEAM_EXE}')
            return
        for item in windows:
            index = self.windows.findData(item['hwnd'])
            label = f'Steam · PID {item["pid"]} · HWND {item["hwnd"]} · {item["title"]}'
            if index < 0:
                self.windows.addItem(label, item['hwnd'])
            else:
                self.windows.setItemText(index, label)
        self.windows.setCurrentIndex(self.windows.findData(windows[0]['hwnd']))
        item = windows[0]
        def ready():
            self.use_client_area()
            l, t, r, b = win.client_rect(self.bound)
            self.report(f'Steam пробуждён: PID {item["pid"]}, HWND {item["hwnd"]}, клиент {r-l}×{b-t}. '
                        'Нажмите «Начать трансляцию».')
        self.pending_activation = dict(wake=WindowWake(self.bound), action=ready)
        self.report('Пробуждаю найденное Steam-окно…')

    def use_client_area(self):
        if not self.bound:
            raise RuntimeError('Сначала выберите окно.')
        l, t, r, b = win.client_rect(self.bound)
        self.set_area((0, 0, r-l, b-t))

    def report(self, text):
        self.status.setText(text)
        self.log.append(f'{datetime.now():%H:%M:%S}  {text}')

    def guard(self, function):
        try:
            function()
        except Exception as exc:
            try:
                self.cancel()
            except Exception as cleanup:
                self.report(f'Ошибка освобождения ввода: {cleanup}')
            self.report(f'ОШИБКА: {exc}')

    def find_chrome(self):
        self.cancel()
        windows = win.chrome_windows()
        windows.sort(key=lambda item: not any(word in item[1].casefold()
                                             for word in ('dungeon crusher', 'дробители подземелий')))
        self.windows.clear()
        self.windows.addItem('Без привязки — весь рабочий стол', None)
        for hwnd, title in windows:
            game = any(word in title.casefold() for word in ('dungeon crusher', 'дробители подземелий'))
            self.windows.addItem(f'{"[ИГРА] " if game else ""}{title} [HWND {hwnd}]', hwnd)
        self.report(f'Найдено окон Chrome: {len(windows)}. Выберите игровое окно в списке.')

    def bind_selected(self, index):
        self.guard(lambda: self._bind(index))

    def _bind(self, index):
        self.stop_live()
        self.cancel()
        self.bound = self.windows.itemData(index) if index >= 0 else None
        self.point = None
        self.point_geometry = None
        self.relative_point = None
        self.area = None
        self.area_label.setText('Игровая область не задана: выполните калибровку.')
        self.saved.setText('Записанная точка: нет (после смены окна запишите заново)')
        self.bound_label.setText(f'Привязано: {win.title(self.bound)}' if self.bound
                                 else 'Без привязки: действия разрешены на рабочем столе.')
        if self.bound:
            _, pid = win.identity(self.bound)
            self.bound_label.setText(f'PID {pid} · HWND {self.bound} · {win.title(self.bound)}')

    def toggle_coordinates(self):
        self.show_position = not self.show_position
        self.coordinates.setText('Координаты мыши: ' + str(win.position()))

    def record(self):
        self.cancel()
        if self.bound:
            if not self.area:
                raise RuntimeError('Сначала откалибруйте игровую область выбранного окна.')
            self.area.rectangle()
        self.recorder.start()
        self.report('Ожидается ровно один физический левый клик. Исходный клик проходит в окно.')

    def on_recorded(self, point):
        self.guard(lambda: self.accept_recorded(point))

    def accept_recorded(self, point):
        # A queued hook signal after STOP must not restore a cancelled recording.
        if not self.recorder.handle:
            return
        self.recorder.stop()
        if win.root_at(point) == int(self.winId()):
            self.report('Первый клик пришёлся на Launcher. Запись остановлена; выберите точку вне него.')
            return
        if self.bound and win.root_at(point) != self.bound:
            self.report('Первый клик вне привязанного окна. Запись остановлена, точка не изменена.')
            return
        relative = self.area.relative(point) if self.bound and self.area else None
        self.relative_point = relative
        self.point = tuple(point)
        self.point_geometry = win.rect(self.bound) if self.bound else None
        self.saved.setText(f'Записанная точка Windows: X={point[0]}, Y={point[1]}')
        if relative is not None:
            self.saved.setText(f'Точка относительно игры: X={relative[0]}, Y={relative[1]}')
        self.report('Один клик записан. Запись выключена.')

    def validate_target(self):
        if self.point is None:
            raise RuntimeError('Сначала запишите точку.')
        if self.bound:
            if not win.user32.IsWindow(self.bound) or win.user32.IsIconic(self.bound):
                raise RuntimeError('Привязанное окно закрыто или свёрнуто.')
            if not self.area or self.relative_point is None or self.area.hwnd != self.bound:
                raise RuntimeError('Откалибруйте игровую область и запишите точку заново.')
            absolute = self.area.absolute(self.relative_point)
            if self.operation and absolute != self.point:
                raise RuntimeError('Окно переместилось во время действия. Действие отменено; запустите его заново.')
            self.point = absolute
            if win.user32.GetForegroundWindow() != self.bound or win.root_at(self.point) != self.bound:
                raise RuntimeError('Привязанное окно не активно или целевая точка перекрыта другим окном.')

    def begin(self, click, from_route=False, fast=False):
        self.cancel(cancel_route=not from_route)
        if self.point is None:
            raise RuntimeError('Сначала запишите точку.')
        if win.user32.GetAsyncKeyState(1) & 0x8000:
            raise RuntimeError('Отпустите левую кнопку мыши перед запуском.')
        if self.bound:
            self.operation = dict(phase='wake', wake=WindowWake(self.bound), click=click, fast=fast)
            self.report('Пробуждаю игровое окно перед действием…')
            return
        self.validate_target()
        self.operation = dict(phase='countdown', due=time.monotonic() + 1.0, click=click)
        self.report('Старт через 1 секунду. Для отмены удерживайте Esc или нажмите СТОП.')

    def tick(self):
        self.guard(self.advance)

    def advance(self):
        if self.show_position:
            x, y = win.position()
            self.coordinates.setText(f'Координаты Windows: X={x}, Y={y}')
        if (self.operation or self.recorder.handle or self.held or self.capture_timer.isActive()
                or self.calibration_dialog or self.pending_activation) and win.user32.GetAsyncKeyState(0x1B) & 0x8000:
            self.stop()
            return
        if self.pending_activation:
            pending = self.pending_activation
            if pending['wake'].poll():
                self.pending_activation = None
                pending['action']()
            return
        op = self.operation
        if not op:
            return
        if op['phase'] == 'wake':
            if not op['wake'].poll():
                return
            # Translate relative point AFTER a minimized window has been restored.
            if self.area and self.relative_point is not None:
                self.point = self.area.absolute(self.relative_point)
            self.validate_target()
            op.update(phase='countdown', due=time.monotonic()+(.02 if op.get('fast') else .4))
            self.report('Игровое окно активно; положение и фокус проверены.')
            return
        self.validate_target()
        now = time.monotonic()
        if op['phase'] == 'countdown' and now >= op['due']:
            op.update(phase='moving', start=now, origin=win.position())
            op['duration'] = max(0.08, math.dist(op['origin'], self.point) / 6000) if op.get('fast') else max(0.2, math.dist(op['origin'], self.point) / self.speed.value())
        if op['phase'] == 'moving':
            fraction = min(1.0, (now - op['start']) / op['duration'])
            target = tuple(round(a + (b - a) * fraction) for a, b in zip(op['origin'], self.point))
            win.move(*target)
            if fraction >= 1:
                op.update(phase='verify', due=now + 0.3)
        elif op['phase'] == 'verify':
            actual = win.position()
            if actual != self.point:
                if now >= op['due']:
                    raise RuntimeError(f'GetCursorPos={actual}, ожидалось {self.point}. Действие отменено.')
            else:
                if not op['click']:
                    self.operation = None
                    self.report(f'Перемещение подтверждено GetCursorPos: {actual}.')
                else:
                    pause = .08 if op.get('fast') else self.pause.value()
                    op.update(phase='pause', due=now + pause)
                    self.report(f'Курсор в {actual}. Пауза {pause:.2f} с перед кликом…')
        elif op['phase'] == 'pause' and now >= op['due']:
            if win.position() != self.point:
                raise RuntimeError('Курсор сдвинут во время паузы. Клик отменён.')
            if win.user32.GetAsyncKeyState(1) & 0x8000:
                raise RuntimeError('Левая кнопка уже удерживается. Клик отменён.')
            if op.get('check_before_click'):
                op['check_before_click']()
                self.validate_target()
            win.send(0x0002)
            self.held = True
            op.update(phase='release', due=now + 0.06)
        elif op['phase'] == 'release' and now >= op['due']:
            self.release()
            self.operation = None
            self.report(f'SendInput принял один mouseDown/mouseUp в {self.point}; '
                        'положение проверено. Реакцию целевого окна проверьте визуально.')

    def release(self):
        if self.held:
            win.send(0x0004)
            self.held = False

    def cancel(self, cancel_route=True):
        self.pending_activation = None
        if cancel_route and self.siege:
            self.siege.cancel()
        self.operation = None
        self.capture_timer.stop()
        if self.calibration_dialog:
            self.calibration_dialog.reject()
        try:
            self.recorder.stop()
        finally:
            self.release()

    def stop(self):
        self.stop_live()
        self.cancel()
        self.report('СТОП: ожидающие действия отменены, запись выключена, кнопка освобождена.')

    def request_capture(self, calibration=False):
        if calibration:
            self.stop_live()
        self.cancel()
        if calibration and not self.bound:
            raise RuntimeError('Сначала выберите окно.')
        if self.bound:
            if not win.user32.IsWindow(self.bound) or win.user32.IsIconic(self.bound):
                raise RuntimeError('Окно закрыто или свёрнуто.')
            if not win.user32.SetForegroundWindow(self.bound):
                raise RuntimeError('Не удалось активировать привязанное окно.')
        self.capture_calibration = calibration
        self.capture_timer.start(400)
        self.report('Подготовка снимка через 0,4 с. СТОП отменяет захват.')

    def complete_capture(self):
        if not self.capture_calibration:
            self.screenshot()
            self.raise_()
            self.activateWindow()
            return
        hwnd = self.bound
        geometry = win.client_rect(hwnd)
        signature = (win.identity(hwnd), win.user32.GetDpiForWindow(hwnd), win.title(hwnd))
        l, t, r, b = geometry
        image = self.capture_region(dict(left=l, top=t, width=r-l, height=b-t))
        self.show_preview(image, 'Снимок окна для калибровки')
        dialog = CalibrationDialog(image, self)
        self.calibration_dialog = dialog
        try:
            accepted = dialog.exec() == QDialog.Accepted
        finally:
            self.calibration_dialog = None
        if not accepted:
            self.report('Калибровка отменена; предыдущая область сохранена.')
            return
        if hwnd != self.bound or geometry != win.client_rect(hwnd) or signature != (
                win.identity(hwnd), win.user32.GetDpiForWindow(hwnd), win.title(hwnd)):
            raise RuntimeError('Окно изменилось после снимка. Повторите калибровку.')
        self.set_area(dialog.selection.crop())

    def set_area(self, crop):
        self.stop_live()
        area = GameArea.create(self.bound, crop)
        self.area = area
        self.point = self.relative_point = None
        x, y, w, h = crop
        self.area_label.setText(f'Область: ({x}, {y}), {w}×{h} пикселей; DPI {area.dpi}.')
        self.saved.setText('Область изменена: запишите точку заново.')
        self.report('Игровая область привязана к окну. Перемещение окна учитывается автоматически.')

    def capture_region(self, region):
        before = None
        if self.bound:
            before = (win.identity(self.bound), win.client_rect(self.bound), win.title(self.bound),
                      win.user32.GetDpiForWindow(self.bound))
            if win.user32.IsIconic(self.bound) or win.user32.GetForegroundWindow() != self.bound:
                raise RuntimeError('Для снимка привязанное окно должно быть активным и не свёрнутым.')
            l, t, w, h = (region[k] for k in ('left', 'top', 'width', 'height'))
            for x in (l, l+w//2, l+w-1):
                for y in (t, t+h//2, t+h-1):
                    if win.root_at((x, y)) != self.bound:
                        raise RuntimeError('Область вне экрана или перекрыта другим окном. Уберите перекрытие.')
        with mss.MSS() as capture:
            shot = capture.grab(region)
            image = QImage(shot.rgb, shot.width, shot.height, shot.width*3, QImage.Format_RGB888).copy()
        if before is not None and before != (
                win.identity(self.bound), win.client_rect(self.bound), win.title(self.bound),
                win.user32.GetDpiForWindow(self.bound)):
            raise RuntimeError('Окно изменилось во время захвата. Снимок отклонён.')
        return image

    def show_preview(self, image, description):
        self.preview_image = image
        self.preview_info.setText(f'{description}\n{image.width()}×{image.height()} физических пикселей')
        self.update_preview()

    def update_preview(self):
        if self.preview_image is not None:
            image = self.preview_image
            result = self.vision.result if self.vision else None
            if result and result.get('cards') and time.perf_counter()-result['received'] < .6 and self.live and self.live.isRunning():
                image = image.copy()
                painter = QPainter(image)
                painter.setPen(QPen(QColor('#00bfff'), 5))
                font = painter.font()
                font.setPixelSize(26)
                painter.setFont(font)
                for number, card in enumerate(result['cards'], 1):
                    x,y,w,h = card['rect']
                    painter.drawRect(x,y,w,h)
                    painter.drawText(x+8,y+30,f'Босс {number}')
                painter.end()
            if result and result['track'] and time.perf_counter()-result['received'] < .6 and self.live and self.live.isRunning():
                image = image.copy()
                painter = QPainter(image)
                painter.setPen(QPen(QColor('#00ff88'), 6))
                x, y, w, h = result['track']['rect']
                painter.drawRect(x-6, y-6, w+12, h+12)
                painter.end()
            self.preview.setPixmap(QPixmap.fromImage(image).scaled(
                self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'preview_image'):
            self.update_preview()

    def screenshot(self):
        folder = BASE / 'screenshots'
        folder.mkdir(exist_ok=True)
        path = folder / f'capture-{datetime.now():%Y%m%d-%H%M%S-%f}.png'
        if self.bound:
            if not self.area:
                raise RuntimeError('Сначала откалибруйте игровую область.')
            l, t, w, h = self.area.rectangle()
            region = dict(left=l, top=t, width=w, height=h)
        else:
            with mss.MSS() as capture:
                region = capture.monitors[0]
        image = self.capture_region(region)
        if not image.save(str(path), 'PNG'):
            raise RuntimeError('Не удалось сохранить PNG.')
        self.last_screenshot = str(path)
        self.show_preview(image, str(path))
        self.report(f'PNG сохранён ({image.width()}×{image.height()}): {path}.')

    def closeEvent(self, event):
        if self.vision:
            self.vision.requestInterruption()
            self.vision.wait()
        if self.live and self.live.isRunning():
            self._closing = True
            self.stop_live()
            self.cancel()
            event.ignore()
            return
        try:
            self.cancel()
        except Exception as exc:
            self.report(f'Ошибка остановки: {exc}. Закрытие отменено.')
            event.ignore()
            return
        if self.demo_window:
            self.demo_window.close()
        if not getattr(self,'_store_closed',False):
            self.boss_store.close()
            self._store_closed=True
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = Launcher()
    window.show()
    if '--bosses' in sys.argv:
        window.open_boss_panel()
    if '--selfcheck' in sys.argv:
        from selfcheck import run
        run(app, window)
    if '--live-demo' in sys.argv or '--live-benchmark' in sys.argv:
        window.open_demo()
        QTimer.singleShot(600, lambda: window.guard(window.start_live))
    if '--live-benchmark' in sys.argv:
        from live_benchmark import run
        run(app, window)
    if '--steam-live' in sys.argv or '--steam-check' in sys.argv:
        window.find_steam()
        if window.bound:
            QTimer.singleShot(600, lambda: window.guard(window.start_live))
    if '--steam-check' in sys.argv:
        from steam_check import run
        run(window)
    if '--siege-selfcheck' in sys.argv:
        from siege_selfcheck import run
        QTimer.singleShot(500, lambda: run(app, window))
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
