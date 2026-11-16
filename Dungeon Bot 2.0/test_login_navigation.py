import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np
from autopilot import SiegeNavigation
from siege import ButtonMatcher


class GoldRecognitionTests(unittest.TestCase):
    def test_home_without_events_and_original_layout(self):
        from build_siege_assets import read_reference
        photo = cv2.imdecode(np.fromfile(Path(__file__).parent/'tests/fixtures/home-no-events.jpg', np.uint8), 1)
        frame = cv2.resize(photo, (1920, 1080))
        matcher = ButtonMatcher()
        hit = matcher.find(frame, 'home')
        self.assertIsNotNone(hit)
        self.assertTrue(670 < hit['point'][0] < 730)
        self.assertTrue(500 < hit['point'][1] < 590)
        self.assertIsNotNone(matcher.find(read_reference(0), 'home'))
        # Leagues and the other sidebar icons must not substitute for Sieges.
        frame[495:620, 650:750] = 0
        self.assertIsNone(matcher.find(frame, 'home'))

    def test_photo_and_different_gold_amount(self):
        photo = cv2.imdecode(np.fromfile(Path(__file__).parent/'tests/fixtures/offline-gold.jpg', np.uint8), 1)
        frame = cv2.resize(photo, (1920, 1080))
        matcher = ButtonMatcher()
        for changed in (False, True):
            if changed:
                frame[475:510, 930:1040] = (105, 174, 214)
            hit = matcher.find(frame, 'offline_gold_ok')
            self.assertIsNotNone(hit)
            self.assertLessEqual(abs(hit['point'][0] - 960), 2)
            self.assertLessEqual(abs(hit['point'][1] - 560), 2)
        frame[395:463, 795:1125] = 0
        self.assertIsNone(matcher.find(frame, 'offline_gold_ok'))

    def test_other_screens_do_not_match(self):
        from build_siege_assets import read_reference
        matcher = ButtonMatcher()
        for index in range(7):
            source = read_reference(index)
            frame = np.zeros((1080, 1920, 3), np.uint8)
            frame[:source.shape[0], :source.shape[1]] = source
            self.assertIsNone(matcher.find(frame, 'offline_gold_ok'))


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.visible = set()
        self.frame = SimpleNamespace(sequence=1, received=time.perf_counter(), image=None)
        self.ui = SimpleNamespace(operation=None, autopilot=Mock(), cancel=Mock())
        self.ui.begin = Mock(side_effect=lambda *a, **k: setattr(self.ui, 'operation', {}))
        self.route = SiegeNavigation.__new__(SiegeNavigation)
        self.route.ui = self.ui
        self.route.active = True
        self.route.phase = 'observe'
        self.route.expires = time.monotonic()+120
        self.route.last_sequence = -1
        self.route.waiting_key = None
        self.route.click_pending = False
        self.route.destination = None
        self.route.wake = SimpleNamespace(ready_at=0)
        self.route.area = SimpleNamespace(absolute=lambda point: point)
        self.route.frame = Mock(return_value=self.frame)
        self.route.wait_for_video = Mock(return_value=False)
        self.route.cancel = Mock()
        self.route.pre_click = Mock()
        self.route.matcher = SimpleNamespace(
            find=lambda image, key: {'point': (960, 560)} if key in self.visible else None,
            battle_ready=lambda image: None)
        patcher = patch('autopilot.pixels', return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tick(self):
        self.frame.sequence += 1
        self.route.tick()

    def finish_click(self, key):
        self.ui.operation['check_before_click']()
        self.route.pre_click.assert_called_with(key, (960, 560))
        self.ui.operation = None
        self.tick()

    def test_gold_home_ranking_list_and_no_duplicate_click(self):
        self.visible = {'offline_gold_ok', 'home', 'track'}
        self.tick()
        self.assertEqual(self.route.waiting_key, 'offline_gold_ok')
        self.assertIsNone(self.route.destination)
        self.finish_click('offline_gold_ok')
        self.tick()
        self.assertEqual(self.ui.begin.call_count, 1)
        self.visible = {'home'}
        self.tick()
        self.finish_click('home')
        self.tick()
        self.assertEqual(self.ui.begin.call_count, 2)
        self.visible = {'ranking'}
        self.tick()
        self.finish_click('ranking')
        self.visible = {'track'}
        self.tick()
        self.assertEqual(self.route.destination, 'list')
        self.assertEqual(self.ui.begin.call_count, 3)

    def test_no_popup_and_already_open_list(self):
        self.visible = {'home'}
        self.tick()
        self.assertEqual(self.route.waiting_key, 'home')
        self.finish_click('home')
        self.visible = {'card'}
        self.tick()
        self.assertEqual(self.route.destination, 'list')

    def test_old_frame_cannot_advance_after_click(self):
        self.visible = {'offline_gold_ok'}
        self.tick()
        self.finish_click('offline_gold_ok')
        self.visible = {'home'}
        self.route.tick()
        self.assertEqual(self.ui.begin.call_count, 1)


if __name__ == '__main__':
    unittest.main()
