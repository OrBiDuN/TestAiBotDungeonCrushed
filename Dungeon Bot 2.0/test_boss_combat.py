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
        with self.assertRaises(RuntimeError):self.cycle.tick()
        self.assertEqual(self.ended,[])

    def test_cross_requires_battle_screen(self):
        self.cycle.phase='battle'
        self.frame.image={'battle_close'}
        self.cycle.tick();self.assertIsNone(self.ui.operation)

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

if __name__=='__main__':unittest.main()
