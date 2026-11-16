import unittest
from unittest.mock import patch
from types import SimpleNamespace
from bosscombat import CombatCycle

class CombatTests(unittest.TestCase):
    def setUp(self):
        self.now=10
        self.clock=patch('bosscombat.time.monotonic',lambda:self.now);self.clock.start()
        self.pixel=patch('bosscombat.pixels',lambda x:x);self.pixel.start()
        self.frame=SimpleNamespace(sequence=1,image={'normal'})
        self.ui=SimpleNamespace(operation=None)
        self.ui.begin=lambda *a,**k:setattr(self.ui,'operation',{})
        self.ui.cancel=lambda **k:setattr(self.ui,'operation',None)
        self.ended=[];self.logs=[]
        self.route=SimpleNamespace(ui=self.ui,frame=lambda:self.frame,area=SimpleNamespace(absolute=lambda p:p),
            matcher=SimpleNamespace(find=lambda image,key:dict(point=(10,20)) if key in image else None),
            log=lambda *a,**k:self.logs.append((a,k)),cancel=self.ended.append)
        self.cycle=CombatCycle(self.route)

    def tearDown(self):self.pixel.stop();self.clock.stop()

    def click_and_observe(self,scene):
        callback=self.ui.operation['check_before_click'];callback()
        with self.assertRaises(RuntimeError):callback()
        self.ui.operation=None;self.cycle.tick()
        self.frame.sequence+=1;self.frame.image=set(scene);self.now+=.5
        self.cycle.tick()

    def test_two_attacks_crosses_and_completed_back(self):
        self.cycle.tick()
        self.click_and_observe({'battle_close','battle_turn'})
        self.assertEqual(self.cycle.next_phase,'return_menu')
        self.click_and_observe({'normal'})
        self.assertEqual(self.cycle.next_phase,'battle')
        self.click_and_observe({'battle_close','battle_turn'})
        self.click_and_observe({'boss_done','boss_back'})
        self.assertEqual(self.cycle.next_phase,'list')
        self.click_and_observe({'card'})
        self.assertEqual(self.cycle.attacks,2)
        self.assertEqual(len(self.ended),1)
        self.assertEqual([event[0][0] for event in self.logs],[
            'Цикл босса: normal','Цикл босса: battle_close','Цикл босса: normal',
            'Цикл босса: battle_close','Цикл босса: boss_back'])

    def test_missing_attack_is_not_completion(self):
        self.frame.image={'boss_back'}
        self.cycle.tick();self.assertIsNone(self.ui.operation)
        self.now=26
        self.cycle.tick()
        self.assertEqual(self.cycle.phase,'recover')
        self.assertEqual(self.ended,[])

    def test_endless_archives_menu_before_each_attack_and_finished_before_back(self):
        shots = []
        self.route.endless = True
        self.route.save_endless_frame = lambda frame, stage, attack: shots.append(
            (set(frame.image), stage, attack))
        self.cycle.tick()
        self.click_and_observe({'battle_close', 'battle_turn'})
        self.click_and_observe({'normal'})
        self.click_and_observe({'battle_close', 'battle_turn'})
        self.click_and_observe({'boss_done', 'boss_back'})
        self.click_and_observe({'card'})
        self.assertEqual(shots, [({'normal'}, 'menu', 1),
                                 ({'normal'}, 'menu', 2),
                                 ({'boss_done', 'boss_back'}, 'finished', 0)])

    def observe_recovery(self, scene):
        self.frame.image=set(scene)
        for _ in range(4):
            self.now+=.6;self.frame.sequence+=1;self.cycle.tick()

    def test_disappeared_close_recovers_to_menu_without_clicking_old_point(self):
        self.cycle.send('battle_close',(10,20),'return_menu')
        self.frame.image={'normal'}
        with self.assertRaises(RuntimeError):self.ui.operation['check_before_click']()
        self.cycle.recover('button vanished')
        self.assertIsNone(self.ui.operation)
        self.observe_recovery({'normal'})
        self.assertEqual(self.cycle.phase,'click')
        self.assertEqual(self.cycle.next_phase,'battle')
        self.assertEqual(self.cycle.attempts,set())

    def test_unknown_screen_waits_and_then_recovers_to_battle(self):
        self.cycle.recover('timeout')
        self.observe_recovery(set())
        self.assertEqual(self.cycle.phase,'recover')
        self.assertIsNone(self.ui.operation)
        self.observe_recovery({'battle_close'})
        self.assertEqual(self.cycle.phase,'click')
        self.assertEqual(self.cycle.next_phase,'return_menu')

    def test_recovery_does_not_resend_attack_with_unknown_outcome(self):
        self.cycle.tick();self.ui.operation['check_before_click']()
        self.cycle.recover('timeout')
        self.observe_recovery({'normal'})
        self.assertEqual(self.cycle.phase,'recover')
        self.assertIsNone(self.ui.operation)

    def test_cross_requires_battle_screen(self):
        self.cycle.phase='battle'
        self.frame.image={'battle_close'}
        self.cycle.tick();self.assertIsNone(self.ui.operation)

    def test_one_retry_when_cross_remains_on_fresh_battle_frame(self):
        self.cycle.tick()
        self.click_and_observe({'battle_close','battle_turn'}) # ordinary attack -> battle
        self.click_and_observe({'battle_close','battle_turn'}) # first close did not leave battle
        self.assertEqual(self.cycle.phase,'click')
        self.assertIsNotNone(self.ui.operation)
        self.assertEqual(self.cycle.close_retries,1)
        self.click_and_observe({'normal'})
        self.assertEqual(self.cycle.close_retries,1)

    def test_cross_is_not_retried_more_than_once(self):
        self.cycle.phase='return_menu';self.cycle.battle_expected=True;self.cycle.close_retries=1
        self.frame.image={'battle_close','battle_turn'}
        self.cycle.tick()
        self.assertIsNone(self.ui.operation)

    def test_moved_battle_button_retargets_before_any_click(self):
        self.frame.image={'battle_close'}
        self.cycle.send('battle_close',(10,20),'return_menu')
        callback=self.ui.operation['check_before_click']
        self.route.matcher.find=lambda image,key:dict(point=(30,40)) if key=='battle_close' else None
        self.assertEqual(callback(),'retarget')
        self.assertEqual(self.ui.point,(30,40))
        self.assertEqual(self.cycle.attempts,set())
        self.assertIsNone(callback())
        self.assertEqual(self.cycle.attempts,{(0,'battle_close')})

    def test_completed_boss_does_not_get_another_attack(self):
        self.frame.image={'boss_done','boss_back'}
        self.cycle.tick()
        self.assertEqual(self.cycle.next_phase,'list')
        self.click_and_observe({'track'})
        self.assertEqual(self.cycle.attacks,0)
        self.assertEqual(len(self.ended),1)

    def test_completed_boss_can_hand_off_to_endless_route(self):
        handed=[]
        self.route.on_combat_finished=lambda: handed.append(True)
        self.frame.image={'boss_done','boss_back'}
        self.cycle.tick()
        self.click_and_observe({'track'})
        self.assertEqual(handed,[True])
        self.assertEqual(self.ended,[])

    def test_failed_attack_popup_has_priority_then_back_and_endless(self):
        handed=[]
        self.route.on_combat_finished=lambda:handed.append(True)
        self.cycle.tick()
        self.click_and_observe({'attack_failed_ok','boss_done','boss_back'})
        self.assertEqual(self.cycle.next_phase,'popup_wait')
        self.click_and_observe({'boss_done','boss_back'})
        self.assertEqual(self.cycle.next_phase,'list')
        self.click_and_observe({'track'})
        self.assertEqual(handed,[True])
        self.assertEqual(self.cycle.attacks,1)

    def test_popup_in_recovery_and_retry_only_on_new_frames(self):
        self.cycle.recover('timeout')
        self.now+=1
        self.frame.image={'attack_failed_ok','boss_done','boss_back'}
        self.cycle.tick()
        self.assertEqual(self.cycle.next_phase,'popup_wait')
        self.click_and_observe(self.frame.image)
        self.assertIsNone(self.ui.operation)
        self.now+=2;self.frame.sequence+=1
        self.cycle.tick()
        self.assertEqual(self.cycle.popup_attempt,2)
        self.assertEqual(self.cycle.next_phase,'popup_wait')

    def test_popup_appearing_before_back_blocks_underlying_click(self):
        self.frame.image={'boss_done','boss_back'}
        self.cycle.tick()
        self.frame.image.add('attack_failed_ok')
        with self.assertRaisesRegex(RuntimeError,'сначала требуется ОК'):
            self.ui.operation['check_before_click']()
        self.assertEqual(self.cycle.attempts,set())

if __name__=='__main__':unittest.main()
