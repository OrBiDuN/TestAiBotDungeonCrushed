import unittest,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import cv2,numpy as np
from PySide6.QtWidgets import QApplication
from bossocr import BossReader
from cardvision import CardDetector
from bosssearch import BossSearch
from launcher import Launcher

class BossReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def test_russian_names_scores_and_partial_card(self):
        reader=BossReader()
        for name,expected_count in [('e6054eaf-6dc6-4750-b541-3c29ec305967',3),('dc4ac507-5722-4322-83c6-a61820fe1fbe',4)]:
            p=(Path(__file__).parent/'tests'/'fixtures')/f'codex-clipboard-{name}.png'
            image=cv2.imdecode(np.fromfile(p,np.uint8),1)
            rows=reader.read(image,CardDetector().detect(image))
            self.assertEqual(len(rows),expected_count)
            self.assertEqual([(r['name'],r['points']) for r in rows[:3]],
                [('Лаксир',2445),('Лаксир',2445),('Озехн',1785)])
            if expected_count==4:
                self.assertTrue(rows[3]['partial'])
                self.assertIsNone(rows[3]['name'])

    def test_read_first_card_then_one_click_and_confirm(self):
        ui=Launcher();route=BossSearch(ui);ui.siege=route
        route.active=True;route.phase='read_boss';route.sent_sequence=5
        route.read_deadline=time.monotonic()+8
        route.ready=0;route.read_min_time=0;route.read_signature=None
        route.area=SimpleNamespace(absolute=lambda point:point)
        row=dict(partial=False,valid=True,points=2445,attack=(1140,416),name='Лаксир')
        ui.vision=SimpleNamespace(ocr_result=dict(error=None,received=time.perf_counter(),sequence=6,rows=[row]))
        ui.begin=lambda *args,**kwargs:setattr(ui,'operation',{})
        route.verify_boss_click=lambda value:self.assertEqual(value['attack'],row['attack'])
        frame=SimpleNamespace(image=None,sequence=6,received=time.perf_counter())
        route.frame=lambda:frame
        route.card_detector=SimpleNamespace(detect=lambda _: [dict(partial=False,attack=(1140,416),anchor=(1080,402))])
        route.matcher.find=lambda *_:True
        try:
            with patch('bosssearch.win.user32.GetAsyncKeyState',return_value=0),patch('bosssearch.pixels',lambda image:image),patch('bossocr.fingerprint',return_value='stable'):
                route.tick()
                self.assertEqual(route.phase,'read_boss')
                frame.sequence=7
                route.card_stable_since-=.4
                route.tick()
                self.assertEqual(route.phase,'boss_click')
                self.assertEqual(ui.point,(1140,416))
                ui.operation['check_before_click']()
                ui.operation=None
                route.tick();self.assertEqual(route.phase,'confirm_boss')
                route.tick();self.assertFalse(route.active)
        finally:
            ui.vision=None;ui.close()

if __name__=='__main__':unittest.main()
