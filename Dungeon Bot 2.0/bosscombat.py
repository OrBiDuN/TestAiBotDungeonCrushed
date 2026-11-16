"""Confirmed menu -> ordinary attack -> battle close -> menu -> completion/back."""
import time
import cv2
import numpy as np
from siege import SiegeRoute,pixels
import winmouse as win

class CombatCycle:
    def __init__(self, route):
        self.route=route
        self.phase='menu'
        self.deadline=time.monotonic()+10
        self.expires=time.monotonic()+600
        self.attacks=0
        self.attempts=set()
        self.sequence=-1
        self.identity=None
        self.state='UNKNOWN_STATE'
        self.battle_expected=False
        self.close_retries=0
        self.recovery_number=0
        self.last_command=None
        self.popup_attempt=0
        self.popup_retry_at=0

    def dismiss_popup(self, image):
        hit=self.route.matcher.find(image,'attack_failed_ok')
        if not hit:return False
        # The modal takes priority over all controls visible behind it.
        if time.monotonic()>=self.popup_retry_at:
            self.popup_attempt+=1
            self.route.log('Атака не получилась: осада завершена. Нажимаю ОК и проверяю карточку.')
            self.send('attack_failed_ok',hit['point'],'popup_wait',f'popup-ok-{self.popup_attempt}')
            self.popup_retry_at=time.monotonic()+2
        return True

    def recover(self, reason):
        self.route.ui.cancel(cancel_route=False)
        if self.phase != 'recover':
            self.recovery_number += 1
            self.route.log('Восстановление: '+str(reason)+' Смотрю текущий экран.')
        self.phase='recover'
        self.recovery_scene=None
        self.recovery_sequence=-1
        self.ready=time.monotonic()+.5

    def recover_tick(self):
        now=time.monotonic()
        if now<self.ready:return
        self.ready=now+.5
        try:
            frame=self.route.frame()
        except Exception:
            return  # Keep observing, never click an old frame.
        if frame.sequence<=self.recovery_sequence:return
        image=pixels(frame.image);m=self.route.matcher
        if self.dismiss_popup(image):return
        done=m.find(image,'boss_done')
        close=self.battle_ready(image)
        normal=m.find(image,'normal')
        listing=m.find(image,'track') or m.find(image,'card')
        scene='done' if done else 'battle' if close else 'menu' if normal else 'list' if listing else 'unknown'
        self.recovery_sequence=frame.sequence
        if scene!=self.recovery_scene:
            self.recovery_scene=scene
            self.recovery_since=now
            return
        if now-self.recovery_since<1:return
        self.deadline=now+15;self.expires=now+600
        if scene=='battle':
            self.battle_expected=True
            self.send('battle_close',close['point'],'return_menu',f'recovery-close-{self.recovery_number}')
        elif scene=='done':
            self.phase='return_menu'
        elif scene=='menu':
            # A sent attack whose outcome has not been observed is not resent.
            if self.last_command=='normal' and self.state!='BATTLE_SCREEN':return
            self.phase='return_menu'
        elif scene=='list' and self.state=='BOSS_FINISHED':
            if hasattr(self.route,'on_combat_finished'):self.route.on_combat_finished()
            else:self.route.cancel('Завершение и возврат в список подтверждены.')

    def state_changed(self,state):
        if self.state==state:return
        previous=self.state
        self.state=state
        store=getattr(self.route.ui,'boss_store',None)
        if store:
            detail={'attacks':self.attacks,'instance_id':getattr(self.route,'selected_instance',None)}
            store.record_combat(getattr(self.route,'run_id','manual'),state,detail)
            # An unconfirmed return to the list cannot undo a confirmed death.
            if previous!='BOSS_FINISHED':store.set_status(detail['instance_id'],state,detail)

    def check_identity(self,image):
        # Production frames are arrays; test state-machine doubles have no pixels.
        if not isinstance(image,np.ndarray):return
        portrait=image[50:240,700:885]
        reference=getattr(self.route,'selected_portrait',None)
        if self.identity is None and reference is not None:
            best=-1
            for scale in (.85,.9,1.,1.1,1.15,1.2,1.25,1.3,1.4,1.5):
                template=cv2.resize(reference,None,fx=scale,fy=scale)
                if template.shape[0]<=portrait.shape[0] and template.shape[1]<=portrait.shape[1]:
                    best=max(best,float(cv2.matchTemplate(portrait,template,cv2.TM_CCOEFF_NORMED).max()))
            if best<.88:
                self.state_changed('UNKNOWN_STATE')
                raise RuntimeError('Портрет открытого босса не совпадает с выбранной карточкой; атака отменена.')
        # OCR/text is intentionally not used as a combat guard: the title rendering
        # changes between maps and previously caused valid attacks to be cancelled.

    def battle_ready(self, image):
        probe = getattr(self.route.matcher, 'battle_ready', None)
        return probe(image) if probe else self.route.matcher.find(image, 'battle_close')

    def send(self,key,point,next_phase,attempt_name=None):
        r=self.route;ui=r.ui
        token=(self.attacks,attempt_name or key)
        if token in self.attempts:raise RuntimeError('Повтор неподтверждённой команды боя запрещён.')
        def check():
            nonlocal point
            frame=r.frame();image=pixels(frame.image)
            if key!='attack_failed_ok' and r.matcher.find(image,'attack_failed_ok'):
                raise RuntimeError('Появилось сообщение о завершении осады; сначала требуется ОК.')
            hit=r.matcher.find(image,key)
            if not hit:
                raise RuntimeError('Кнопка боя больше не видна перед кликом.')
            if max(abs(a-b) for a,b in zip(hit['point'],point))>6:
                # The click has not been sent. Return a retarget request to the
                # launcher so it can move the cursor to the fresh position.
                ui.relative_point=hit['point'];ui.point=r.area.absolute(hit['point'])
                r.log('Кнопка боя сместилась; навожу курсор на свежую позицию.',
                      action=key, old_point=point, new_point=hit['point'])
                point = hit['point']
                return 'retarget'
            if key=='battle_close' and not self.battle_ready(image):
                raise RuntimeError('Экран боя не подтверждён.')
            if key=='boss_back' and not r.matcher.find(image,'boss_done'):
                raise RuntimeError('Завершение осады не подтверждено.')
            if key in ('normal','boss_back'):self.check_identity(image)
            if key=='normal' and isinstance(image,np.ndarray):
                store=getattr(ui,'boss_store',None)
                iid=getattr(r,'selected_instance',None)
                if store and iid:
                    import asyncio
                    from bossocr import BossReader,remaining_seconds
                    records=store.rows('SELECT expiry FROM boss_instances WHERE id=?',(iid,))
                    remaining=remaining_seconds(asyncio.run(BossReader().text(image[115:155,885:1220])))
                    if not records or remaining is None or abs(time.time()+remaining-records[0]['expiry'])>6:
                        self.state_changed('UNKNOWN_STATE')
                        raise RuntimeError('Не подтверждён таймер выбранного экземпляра босса; атака отменена.')
            if token in self.attempts:raise RuntimeError('Повтор команды боя запрещён.')
            if getattr(r, 'endless', False) and key in ('normal', 'boss_back'):
                r.save_endless_frame(frame, 'menu' if key == 'normal' else 'finished',
                                     self.attacks + 1 if key == 'normal' else 0)
            self.attempts.add(token)
            self.last_command=key
            self.sequence=frame.sequence
            r.log('Цикл босса: '+key,attack_number=self.attacks+int(key=='normal'))
        ui.relative_point=point;ui.point=r.area.absolute(point)
        ui.begin(True,from_route=True,fast=True)
        ui.operation['check_before_click']=check
        self.next_phase=next_phase;self.phase='click'

    def tick(self):
        r=self.route;now=time.monotonic()
        if self.phase=='recover':
            self.recover_tick();return
        if now>self.expires:
            self.recover('Истекло время наблюдения боя.');return
        if self.phase=='click':
            if r.ui.operation is not None:return
            if self.next_phase=='battle':
                self.attacks+=1
                if isinstance(getattr(r, 'total_attacks', None), int):
                    r.total_attacks += 1
                self.battle_expected=True
                self.close_retries=0
            self.phase=self.next_phase;self.deadline=now+15;self.ready=now+.3
            return
        if now>self.deadline:
            self.recover('Следующий экран не подтверждён.');return
        if now<getattr(self,'ready',0):return
        frame=r.frame()
        if frame.sequence<=self.sequence:return
        image=pixels(frame.image)
        if self.dismiss_popup(image):return
        if self.phase=='popup_wait':
            # A newer frame without the modal is required before any Back/attack.
            self.phase='return_menu'
            self.deadline=now+15
        done=r.matcher.find(image,'boss_done')
        if self.phase in ('menu','return_menu'):
            if done:
                self.check_identity(image)
                self.state_changed('BOSS_FINISHED')
                back=r.matcher.find(image,'boss_back')
                if back:self.send('boss_back',back['point'],'list')
                return
            normal=r.matcher.find(image,'normal')
            if normal:
                self.check_identity(image)
                self.state_changed('BOSS_ACTIVE')
                self.send('normal',normal['point'],'battle')
            elif self.phase=='return_menu' and self.battle_expected:
                close=self.battle_ready(image)
                if close and self.close_retries < 1:
                    self.close_retries += 1
                    self.log_retry()
                    self.send('battle_close',close['point'],'return_menu','battle_close_retry')
            else:
                result=getattr(getattr(r.ui,'vision',None),'ocr_result',None)
                if result and result.get('no_attacks') and time.perf_counter()-result['received']<1.5:
                    self.state_changed('NO_ATTACKS_AVAILABLE')
                    self.recover('Нет доступных атак; ожидаю изменения экрана.')
            return
        if self.phase=='battle':
            close=r.matcher.find(image,'battle_close')
            if self.battle_expected and close and self.battle_ready(image):
                self.state_changed('BATTLE_SCREEN')
                self.send('battle_close',close['point'],'return_menu')
            elif done:
                self.phase='return_menu'
            return
        if self.phase=='list':
            if not done and any(r.matcher.find(image,key) for key in ('track','card')):
                if hasattr(r, 'on_combat_finished'):
                    r.on_combat_finished()
                else:
                    r.cancel('Осада завершена; возврат в список боссов подтверждён.')

    def log_retry(self):
        self.route.log('Крестик боя всё ещё виден на свежем кадре; повторяю нажатие один раз.',
                       retry=self.close_retries)

class BossKill(SiegeRoute):
    def recover_error(self, exc):
        if self.active and self.combat is not None:
            self.combat.recover(exc)
            return True
        return False

    def start_kill(self):
        if self.active:return
        super().start(True)
        self.combat=None
        self.log('Добить босса: обычная атака → крестик → карточка, затем Назад после завершения.')

    def tick(self):
        if not self.active:return
        try:
            if win.user32.GetAsyncKeyState(0x1B)&0x8000:
                self.ui.stop();return
            if self.wait_for_video():return
            if self.combat is None:
                if not self.wake.poll():return
                frame=self.ui.latest_video_frame()
                if not frame or frame.received<self.wake.ready_at or time.perf_counter()-frame.received>.5:
                    if time.perf_counter()-self.wake.started>8:raise RuntimeError('Нет свежего кадра после пробуждения.')
                    return
                self.combat=CombatCycle(self)
            self.combat.tick()
        except Exception as exc:
            if self.recover_error(exc):return
            self.cancel(f'Цикл босса остановлен: {exc}')
            self.ui.cancel()
