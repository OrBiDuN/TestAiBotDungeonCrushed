"""One explicitly selected attack from an already open boss menu."""
import time
from siege import SiegeRoute, LABELS, pixels
import winmouse as win

class BossAttack(SiegeRoute):
    def start_attack(self, key):
        if key not in ('normal','all'):
            raise ValueError('Неизвестная атака.')
        if self.active:
            self.ui.report('Действие уже выполняется.')
            return
        super().start(True)
        self.key=key
        self.log(f'Выбрано одно нажатие «{LABELS[key]}» в открытом меню босса.')

    def tick(self):
        if not self.active: return
        try:
            ui=self.ui
            if win.user32.GetAsyncKeyState(0x1B)&0x8000:
                ui.stop();return
            now=time.monotonic()
            if self.wait_for_video():return
            if self.phase=='wake':
                if not self.wake.poll(): return
                frame=ui.latest_video_frame()
                if not frame or frame.received<self.wake.ready_at or time.perf_counter()-frame.received>.5:
                    if time.perf_counter()-self.wake.started>8:
                        raise RuntimeError('Нет свежего кадра после пробуждения.')
                    return
                self.phase='find'
                self.deadline=now+5
            if self.phase=='find':
                frame=self.frame()
                match=self.matcher.find(pixels(frame.image),self.key)
                if not match:
                    if now>self.deadline:
                        raise RuntimeError(f'Кнопка «{LABELS[self.key]}» не найдена. Откройте меню босса.')
                    return
                point=match['point']
                ui.relative_point=point
                ui.point=self.area.absolute(point)
                ui.begin(True,from_route=True,fast=True)
                ui.operation['check_before_click']=lambda:self.pre_click(self.key,point)
                self.sequence=frame.sequence
                self.phase='click'
                return
            if self.phase=='click':
                if ui.operation is not None:return
                self.phase='confirm'
                self.deadline=now+5
                return
            if self.phase=='confirm':
                frame=self.frame()
                if frame.sequence>self.sequence and not self.matcher.find(pixels(frame.image),self.key):
                    self.cancel(f'«{LABELS[self.key]}» нажата один раз; экран изменился.')
                elif now>self.deadline:
                    self.cancel('Нажатие отправлено, переход не подтверждён. Автоматического повтора нет.')
        except Exception as exc:
            self.cancel(f'Атака остановлена: {exc}')
            self.ui.cancel()
