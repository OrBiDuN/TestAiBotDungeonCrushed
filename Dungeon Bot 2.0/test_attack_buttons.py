import unittest,time
from unittest.mock import patch
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from launcher import Launcher
from bossattack import BossAttack
from siege import ButtonMatcher
from build_siege_assets import read_reference

class AttackButtonsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_templates_are_distinct_and_absent_from_list(self):
        matcher=ButtonMatcher()
        normal=matcher.find(read_reference(4),'normal')
        all_hit=matcher.find(read_reference(4),'all')
        self.assertLess(normal['point'][0],all_hit['point'][0])
        for key in ('normal','all'):
            self.assertIsNone(matcher.find(read_reference(3),key))

    def test_each_choice_sends_only_its_own_attempt(self):
        for key in ('normal','all'):
            with self.subTest(key=key):
                ui=Launcher();r=BossAttack(ui);ui.siege=r
                r.active=True;r.phase='find';r.key=key;r.deadline=time.monotonic()+5
                r.area=SimpleNamespace(absolute=lambda p:p)
                frame=SimpleNamespace(sequence=1,image=None)
                r.frame=lambda:frame
                point=(830,905) if key=='normal' else (1090,905)
                seen=[]
                def find(image,name):
                    seen.append(name)
                    return dict(point=point,score=1)
                r.matcher.find=find
                ui.begin=lambda *a,**kw:setattr(ui,'operation',{})
                try:
                    with patch('bossattack.win.user32.GetAsyncKeyState',return_value=0),patch('bossattack.pixels',lambda x:x),patch('siege.pixels',lambda x:x):
                        r.tick()
                        self.assertEqual(ui.point,point)
                        callback=ui.operation['check_before_click'];callback()
                        self.assertEqual(r.attempts,{key})
                        with self.assertRaises(RuntimeError):callback()
                        ui.operation=None;r.tick()
                        r.deadline=time.monotonic()-1;r.tick()
                        self.assertFalse(r.active)
                        self.assertTrue(all(name==key for name in seen))
                finally:ui.close()

if __name__=='__main__':unittest.main()
