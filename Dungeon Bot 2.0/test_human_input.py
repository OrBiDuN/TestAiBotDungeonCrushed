import random
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import human_input
from launcher import Launcher
from PySide6.QtWidgets import QApplication


class VariationTests(unittest.TestCase):
    def test_bounded_variation_and_no_consecutive_identical_offset(self):
        rng = random.Random(42)
        previous = None
        pauses = []
        for _ in range(1000):
            p = human_input.profile(previous, rng)
            self.assertNotEqual(p['offset'], previous)
            self.assertNotEqual(p['offset'], (0, 0))
            self.assertLessEqual(abs(p['offset'][0]), 3)
            self.assertLessEqual(abs(p['offset'][1]), 2)
            self.assertTrue(.15 <= p['reaction'] <= .45)
            self.assertTrue(.12 <= p['pause'] <= 1.15)
            self.assertTrue(.055 <= p['hold'] <= .115)
            self.assertTrue(30 <= human_input.scroll_interval(rng) <= 320)
            previous = p['offset']
            pauses.append(p['pause'])
        self.assertTrue(any(p > .65 for p in pauses))
        self.assertTrue(any(p < .35 for p in pauses))


class InputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.ui = Launcher()
        self.addCleanup(self.ui.close)
        self.ui.bound = 123
        self.ui.area = SimpleNamespace(absolute=lambda p: (p[0]+100, p[1]+100))
        self.ui.relative_point = (500, 400)
        self.ui.point = (600, 500)
        self.ui.validate_target = Mock()
        self.now = 100.
        self.cursor = (0, 0)
        for name, value in [
            ('launcher.time.monotonic', lambda: self.now),
            ('launcher.win.user32.GetAsyncKeyState', lambda key: 0),
            ('launcher.win.position', lambda: self.cursor),
            ('launcher.win.move', self.move),
        ]:
            p = patch(name, value)
            p.start()
            self.addCleanup(p.stop)
        self.send_patch = patch('launcher.win.send')
        self.send = self.send_patch.start()
        self.addCleanup(self.send_patch.stop)

    def move(self, x, y):
        self.cursor = (x, y)

    def begin(self):
        with patch('launcher.WindowWake', return_value=SimpleNamespace(poll=lambda: True)):
            self.ui.begin(True, from_route=True, fast=True)
        self.check = Mock()
        self.ui.operation['check_before_click'] = self.check

    def reach_pause(self):
        self.ui.advance()  # wake -> countdown
        self.now += 2
        self.ui.advance()  # start moving
        self.now += 2
        self.ui.advance()  # complete moving
        self.ui.advance()  # verify -> pause
        self.assertEqual(self.ui.operation['phase'], 'pause')
        self.check.assert_not_called()
        self.send.assert_not_called()

    def test_delayed_click_is_verified_once_then_released(self):
        self.begin()
        self.assertNotEqual(self.ui.point, (600, 500))
        self.reach_pause()
        self.now = self.ui.operation['due'] - .001
        self.ui.advance()
        self.send.assert_not_called()
        self.now += .002
        self.ui.advance()
        self.check.assert_called_once()
        self.send.assert_called_once_with(2)
        self.now += 1
        self.ui.advance()
        self.assertEqual([c.args[0] for c in self.send.call_args_list], [2, 4])
        self.assertIsNone(self.ui.operation)

    def test_cancel_during_random_pause_sends_nothing(self):
        self.begin()
        self.reach_pause()
        self.ui.cancel()
        self.now += 10
        self.ui.advance()
        self.check.assert_not_called()
        self.send.assert_not_called()

    def test_changed_button_blocks_mouse_down(self):
        self.begin()
        self.reach_pause()
        self.check.side_effect = RuntimeError('button disappeared')
        self.now += 2
        with self.assertRaisesRegex(RuntimeError, 'disappeared'):
            self.ui.advance()
        self.send.assert_not_called()

    def test_retarget_uses_fresh_anchor_with_one_offset(self):
        self.begin()
        offset = self.ui.operation['variation']['offset']
        self.reach_pause()
        def retarget():
            self.ui.relative_point = (700, 600)
            self.ui.point = (800, 700)
            return 'retarget'
        self.check.side_effect = retarget
        self.now += 2
        self.ui.advance()
        self.assertEqual(self.ui.relative_point, (700+offset[0], 600+offset[1]))
        self.assertEqual(self.ui.operation['phase'], 'moving')
        self.send.assert_not_called()

    def test_manual_recorded_click_keeps_exact_position(self):
        with patch('launcher.WindowWake'):
            self.ui.begin(True)
        self.assertEqual(self.ui.point, (600, 500))
        self.assertNotIn('variation', self.ui.operation)


if __name__ == '__main__':
    unittest.main()
