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
        # Fixed portrait/name region excludes timers, HP and participant count.
        patch=image[55:95,885:1140]
        if self.identity is None:self.identity=patch.copy()
        elif patch.shape!=self.identity.shape or np.abs(patch.astype(float)-self.identity).mean()>8:
            self.state_changed('UNKNOWN_STATE')
            raise RuntimeError('Имя открытого босса изменилось; повторная атака отменена.')

    def send(self,key,point,next_phase):
        r=self.route;ui=r.ui
        token=(self.attacks,key)
        if token in self.attempts:raise RuntimeError('Повтор неподтверждённой команды боя запрещён.')
        def check():
            frame=r.frame();image=pixels(frame.image)
            hit=r.matcher.find(image,key)
            if not hit or max(abs(a-b) for a,b in zip(hit['point'],point))>6:
                raise RuntimeError('Кнопка боя сместилась перед кликом.')
            if key=='battle_close' and not r.matcher.find(image,'battle_turn'):
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
            self.attempts.add(token)
            self.sequence=frame.sequence
            r.log('Цикл босса: '+key,attack_number=self.attacks+int(key=='normal'))
        ui.relative_point=point;ui.point=r.area.absolute(point)
        ui.begin(True,from_route=True,fast=True)
        ui.operation['check_before_click']=check
        self.next_phase=next_phase;self.phase='click'

    def tick(self):
        r=self.route;now=time.monotonic()
        if now>self.expires:raise RuntimeError('Достигнуто ограничение 10 минут; цикл остановлен.')
        if self.phase=='click':
            if r.ui.operation is not None:return
            if self.next_phase=='battle':self.attacks+=1
            self.phase=self.next_phase;self.deadline=now+15;self.ready=now+.3
            return
        if now>self.deadline:
            self.state_changed('UNKNOWN_STATE')
            raise RuntimeError('Следующий экран боя не подтверждён. Повтор команды не выполняется.')
        if now<getattr(self,'ready',0):return
        frame=r.frame()
        if frame.sequence<=self.sequence:return
        image=pixels(frame.image)
        done=r.matcher.find(image,'boss_done')
        if self.phase in ('menu','return_menu'):
            if done:
                self.check_identity(image)
                self.state_changed('BOSS_FINISHED')
                back=r.matcher.find(image,'boss_back')
                if back:self.send('boss_back',back['point'],'list')
                return
            if self.attacks>=50:raise RuntimeError('Лимит 50 обычных атак за запуск; цикл остановлен.')
            normal=r.matcher.find(image,'normal')
            if normal:
                self.check_identity(image)
                self.state_changed('BOSS_ACTIVE')
                self.send('normal',normal['point'],'battle')
            else:
                result=getattr(getattr(r.ui,'vision',None),'ocr_result',None)
                if result and result.get('no_attacks') and time.perf_counter()-result['received']<1.5:
                    self.state_changed('NO_ATTACKS_AVAILABLE')
                    r.cancel('Нет доступных атак: подтверждено сообщением игры.')
            return
        if self.phase=='battle':
            close=r.matcher.find(image,'battle_close')
            if close and r.matcher.find(image,'battle_turn'):
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

class BossKill(SiegeRoute):
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
            if self.combat is None:
                if not self.wake.poll():return
                frame=self.ui.latest_video_frame()
                if not frame or frame.received<self.wake.ready_at or time.perf_counter()-frame.received>.5:
                    if time.perf_counter()-self.wake.started>8:raise RuntimeError('Нет свежего кадра после пробуждения.')
                    return
                self.combat=CombatCycle(self)
            self.combat.tick()
        except Exception as exc:
            self.cancel(f'Цикл босса остановлен: {exc}')
            self.ui.cancel()
