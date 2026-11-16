import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import time
import cv2
import numpy as np
from relogin import detect, parse_dialog, still_matches, ReloginRoute


class RecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = cv2.imdecode(np.fromfile(Path(__file__).parent/'tests/fixtures/relogin-phone.jpg', np.uint8), 1)[218:1055]

    def test_supplied_dialog_and_scaled_versions(self):
        for scale in (1, 2, 3):
            with self.subTest(scale=scale):
                image = cv2.resize(self.image, None, fx=scale, fy=scale)
                match = detect(image)
                self.assertIsNotNone(match)
                x, y = match['point']
                self.assertTrue(217*scale < x < 396*scale)
                self.assertTrue(498*scale < y < 550*scale)
                self.assertTrue(still_matches(image, match))
                changed = image.copy()
                rx, ry, w, h = match['rect']
                changed[ry:ry+h, rx:rx+w] = 0
                self.assertFalse(still_matches(changed, match))

    def test_button_without_other_device_message_is_rejected(self):
        self.assertIsNone(parse_dialog([{'text': 'Перезайти', 'rect': (258,514,98,19)}], self.image))

    def test_body_without_button_is_rejected(self):
        image = self.image.copy()
        image[490:560] = 0
        self.assertIsNone(detect(image))


class StateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from launcher import Launcher
        self.ui = Launcher()
        self.ui.vision = SimpleNamespace(relogin_result=None, requestInterruption=lambda: None, wait=lambda: None)
        self.addCleanup(self.ui.close)

    def observe(self, sequence, match):
        self.ui.vision.relogin_result = dict(sequence=sequence, received=time.perf_counter(), match=match, error=None)
        self.ui.poll_relogin()

    def test_dialog_stops_route_and_two_absent_frames_clear_state(self):
        self.ui.siege = Mock(active=True)
        self.observe(1, {'point': (1, 1)})
        self.assertTrue(self.ui.relogin_required)
        self.ui.siege.cancel.assert_called_once()
        self.observe(2, None)
        self.assertTrue(self.ui.relogin_required)
        self.observe(3, None)
        self.assertFalse(self.ui.relogin_required)

    def test_relogin_menu_and_block_endless(self):
        from telegram_control import MENU
        self.ui.telegram = Mock()
        self.ui.relogin_required = True
        self.ui.show_telegram_menu(True)
        self.assertEqual(self.ui.telegram.notify.call_args.kwargs['menu'], MENU)
        with self.assertRaisesRegex(RuntimeError, 'Перезайти'):
            self.ui.start_endless_bosses()

    def test_pre_click_changed_frame_and_duplicate_click_rejected(self):
        route = ReloginRoute(self.ui)
        self.ui.siege = route
        route.sent = False
        route.frame = Mock(return_value=SimpleNamespace(image=None))
        with patch('relogin.pixels', return_value=None), patch('relogin.still_matches', return_value=False):
            with self.assertRaises(RuntimeError):
                route.pre_click_relogin({})
            self.assertFalse(route.sent)
        with patch('relogin.pixels', return_value=None), patch('relogin.still_matches', return_value=True):
            route.pre_click_relogin({})
            with self.assertRaises(RuntimeError):
                route.pre_click_relogin({})


if __name__ == '__main__':
    unittest.main()
