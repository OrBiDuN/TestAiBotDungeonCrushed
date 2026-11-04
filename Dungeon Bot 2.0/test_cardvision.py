import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import cv2,numpy as np
from PySide6.QtWidgets import QApplication
from launcher import Launcher
from bosssearch import BossSearch
from cardvision import CardDetector

class CardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_supplied_three_and_partial_fourth(self):
        for name,count in [('e6054eaf-6dc6-4750-b541-3c29ec305967',3),('dc4ac507-5722-4322-83c6-a61820fe1fbe',4)]:
            p=(Path(__file__).parent/'tests'/'fixtures')/f'codex-clipboard-{name}.png'
            image=cv2.imdecode(np.fromfile(p,np.uint8),1)
            for full in (False,True):
                source=image
                if full:
                    source=np.zeros((1080,1920,3),np.uint8)
                    source[:image.shape[0],680:680+image.shape[1]]=image
                cards=CardDetector().detect(source)
                self.assertEqual(len(cards),count)
                self.assertEqual(cards[-1]['partial'],count==4)

    def test_scroll_three_then_stop_at_four(self):
        ui=Launcher()
        route=BossSearch(ui)
        ui.siege=route
        route.active=True
        route.phase='find'
        route.hwnd=123
        route.sent=0
        route.known_count=0
        route.scrolls=0
        route.previous_point=None
        route.last_sequence=route.sent_sequence=-1
        route.missing_since=None
        route.area=SimpleNamespace(absolute=lambda point:point)
        frame=SimpleNamespace(sequence=1,image=None)
        route.frame=lambda:frame
        cards=[{'rect':(700,230+i*224,530,215),'partial':False} for i in range(3)]
        route.card_detector=SimpleNamespace(detect=lambda _:cards)
        route.matcher.find=lambda *_:None
        ui.begin=lambda *args,**kwargs:setattr(ui,'operation',{})
        ui.validate_target=lambda:None
        try:
            with patch('bosssearch.win.user32.GetAsyncKeyState',return_value=0),patch('bosssearch.win.user32.GetForegroundWindow',return_value=123),patch('bosssearch.pixels',lambda image:image),patch('bosssearch.time.monotonic') as now,patch('bosssearch.scroll_step') as wheel,patch('bosssearch.win.position',lambda:ui.point):
                now.return_value=10
                route.tick()
                frame.sequence=2
                now.return_value=10.7
                route.tick()
                self.assertEqual(route.phase,'scroll_move')
                self.assertIsNotNone(ui.operation)
                wheel.assert_not_called()
                ui.operation=None
                for _ in range(100): route.tick()
                self.assertEqual(wheel.call_count,100)
                wheel.assert_called_with(-1)
                self.assertEqual(route.sent,0)
                cards.append({'rect':(700,900,530,30),'partial':True})
                frame.sequence=3
                now.return_value=11.6
                route.tick()
                self.assertFalse(route.active)
                self.assertEqual(route.known_count,4)
                self.assertEqual(route.sent,0)
                self.assertEqual(wheel.call_count,100)
                route.active=True
                route.open_boss=True
                route.finish_search('Лимит достигнут.')
                self.assertEqual(route.phase,'scroll_move')
                self.assertEqual(route.scroll_direction,1)
                ui.operation=None
                for _ in range(100): route.tick()
                self.assertEqual(wheel.call_count,200)
                wheel.assert_called_with(1)
                self.assertEqual(route.phase,'read_boss')
                self.assertIsNone(ui.operation)
                ui.stop()
                route.tick()
                self.assertEqual(wheel.call_count,200)
        finally:
            ui.close()

if __name__=='__main__': unittest.main()
