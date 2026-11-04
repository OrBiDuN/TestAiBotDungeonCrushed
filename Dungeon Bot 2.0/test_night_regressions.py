import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from launcher import Launcher
from bosssearch import BossSearch

class NightRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.ui=Launcher()
        self.route=BossSearch(self.ui)
        self.ui.siege=self.route
        self.route.active=True
        self.route.area=SimpleNamespace(absolute=lambda point:point)
        self.ui.begin=lambda *a,**k:setattr(self.ui,'operation',{})
        self.keys=patch('bosssearch.win.user32.GetAsyncKeyState',return_value=0)
        self.keys.start()

    def tearDown(self):
        self.keys.stop()
        self.ui.close()

    def test_ocr_deadline_before_early_returns(self):
        r=self.route
        r.phase='read_boss'
        r.read_deadline=time.monotonic()-1
        r.ready=time.monotonic()+100
        r.tick()
        self.assertFalse(r.active)
        self.assertIsNone(self.ui.operation)

    def test_stale_capture_stops_wheel(self):
        r=self.route
        r.phase='scroll_burst'
        r.frame=lambda:(_ for _ in ()).throw(RuntimeError('No fresh frame'))
        with patch('bosssearch.scroll_step') as wheel:
            r.tick()
            wheel.assert_not_called()
        self.assertFalse(r.active)

    def test_changed_capture_cancels_before_mouse_movement(self):
        r=self.route
        r.phase='read_boss'
        r.ready=0
        r.read_deadline=time.monotonic()+8
        r.frame=lambda:(_ for _ in ()).throw(RuntimeError('Capture changed'))
        with patch.object(self.ui,'begin') as begin:
            r.tick()
            begin.assert_not_called()
        self.assertFalse(r.active)

    def test_unknown_points_do_not_block_stable_first_card(self):
        r=self.route
        r.phase='read_boss';r.ready=0;r.read_min_time=0;r.sent_sequence=0
        r.read_deadline=time.monotonic()+8;r.read_signature=None
        frame=SimpleNamespace(image=None,sequence=1,received=time.perf_counter())
        r.frame=lambda:frame
        cards=[dict(attack=(1140,416),anchor=(1080,402),partial=False)]
        r.card_detector=SimpleNamespace(detect=lambda _:cards)
        # OCR failure must not disable visual selection.
        self.ui.vision=SimpleNamespace(ocr_result=dict(error='OCR unavailable',rows=[]))
        try:
            with patch('bosssearch.pixels',lambda x:x),patch('bossocr.fingerprint',return_value='stable'),patch.object(self.ui,'begin') as begin:
                r.tick()
                self.assertIsNotNone(r.read_signature)
                cards.clear();frame.sequence=2;r.tick()
                self.assertIsNone(r.read_signature)
                cards.append(dict(attack=(1140,416),anchor=(1080,402),partial=False))
                frame.sequence=3;r.tick()
                begin.assert_not_called()
                frame.sequence=4;r.card_stable_since-=.4
                begin.side_effect=lambda *a,**k:setattr(self.ui,'operation',{})
                r.tick()
                begin.assert_called_once()
                self.assertEqual(r.phase,'boss_click')
        finally:
            self.ui.vision=None

    def test_one_ordinary_attack_without_retry(self):
        r=self.route
        r.phase='confirm_boss'
        r.confirm_deadline=time.monotonic()+5
        r.attack_once=True
        frame=SimpleNamespace(image=None,sequence=10)
        r.frame=lambda:frame
        match={'point':(830,905),'score':.99}
        r.matcher.find=lambda *_:match
        with patch('bosssearch.pixels',lambda x:x),patch('siege.pixels',lambda x:x):
            r.tick()
            self.assertEqual(r.phase,'ordinary_attack')
            callback=self.ui.operation['check_before_click']
            callback()
            self.assertEqual(r.attempts,{'normal'})
            with self.assertRaises(RuntimeError): callback()
            self.ui.operation=None
            r.tick()
            self.assertEqual(r.phase,'confirm_attack')
            r.confirm_deadline=time.monotonic()-1
            r.tick()
            self.assertFalse(r.active)
            self.assertEqual(r.attempts,{'normal'})
            self.assertIsNone(self.ui.operation)

if __name__=='__main__': unittest.main()
