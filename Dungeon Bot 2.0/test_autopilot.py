import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from autopilot import Autopilot


class AutopilotTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.clock = patch('autopilot.time.monotonic', lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.ui = SimpleNamespace(siege=None, telegram=Mock(), report=Mock(), cancel=Mock(),
            stop_live=Mock(), bound=123, pending_activation=None, relogin_required=False,
            vision=SimpleNamespace(relogin_result={'received': time.perf_counter(), 'error': None}),
            find_steam=Mock(return_value=True), live=None, start_live=Mock(),
            telegram_ready=Mock(return_value=True), status=SimpleNamespace(text=lambda: 'event'))
        self.auto = Autopilot(self.ui)
        self.ui.autopilot = self.auto
        self.windows = patch('targets.steam_windows', return_value=({1: 'game'}, [{'hwnd': 123}]))
        self.probe = self.windows.start()
        self.addCleanup(self.windows.stop)

    def step(self):
        self.now += 1
        self.auto.tick()

    def test_launch_once_wait_for_window_then_capture_and_route(self):
        self.auto.start()
        self.probe.return_value = ({}, [])
        with patch('targets.launch_game') as launch:
            self.step(); self.step()
            launch.assert_called_once()
        self.probe.return_value = ({1: 'game'}, [{'hwnd': 123}])
        self.step()
        self.assertEqual(self.auto.phase, 'capture')
        self.ui.find_steam.assert_called_once()
        self.step()
        self.ui.start_live.assert_called_once()
        self.ui.live = SimpleNamespace(isRunning=lambda: True)
        self.step()
        nav = SimpleNamespace(active=True, start_navigation=Mock(), timer=Mock(), destination=None)
        with patch('autopilot.SiegeNavigation', return_value=nav):
            self.step()
        nav.start_navigation.assert_called_once()
        self.assertEqual(self.auto.phase, 'navigation')
        nav.active = False; nav.destination = 'list'
        self.ui.start_endless_bosses = Mock()
        self.step()
        self.ui.start_endless_bosses.assert_called_once()
        self.assertEqual(self.auto.phase, 'running')

    def test_stop_prevents_launch_and_duplicate_start_keeps_session(self):
        self.auto.start()
        started = self.auto.started
        self.now += 5
        self.auto.start()
        self.assertEqual(self.auto.started, started)
        self.auto.stop()
        with patch('targets.launch_game') as launch:
            self.step()
            launch.assert_not_called()
        self.ui.find_steam.assert_not_called()

    def test_stats_every_ten_minutes_and_counters_survive_route_replacement(self):
        self.auto.start()
        self.auto.phase = 'running'
        self.ui.siege = SimpleNamespace(active=True, completed_bosses=3, total_attacks=7)
        self.ui.telegram.notify.reset_mock()
        self.now = 699
        self.auto.tick()
        self.ui.telegram.notify.assert_not_called()
        self.now = 700
        self.auto.tick()
        self.ui.telegram.notify.assert_called_once()
        self.assertIn('Завершено боссов: 3', self.ui.telegram.notify.call_args.args[0])
        self.ui.siege = SimpleNamespace(active=True, completed_bosses=2, total_attacks=4)
        self.step(); self.step()
        self.assertEqual((self.auto.completed, self.auto.attacks), (5, 11))
        self.ui.telegram.notify.assert_called_once()
        self.auto.stop()
        stats = self.auto.statistics()
        self.now += 600
        self.assertEqual(self.auto.statistics(), stats)

    def test_relogin_resumes_navigation_without_another_user_command(self):
        self.auto.start()
        self.auto.phase = 'running'
        self.ui.siege = SimpleNamespace(active=False)
        self.ui.relogin_required = True
        def relogin():
            self.ui.siege = SimpleNamespace(active=True, succeeded=False)
        self.ui.start_relogin = Mock(side_effect=relogin)
        self.step()
        self.assertEqual(self.auto.phase, 'relogin')
        self.ui.start_relogin.assert_called_once()
        self.ui.siege.active = False
        self.ui.siege.succeeded = True
        self.ui.relogin_required = False
        self.step()
        self.assertEqual(self.auto.phase, 'observe')
        self.assertEqual(self.auto.relogins, 1)

    def test_game_exit_returns_to_launch_and_rebinds_replacement_window(self):
        self.auto.start()
        self.auto.phase = 'running'
        self.probe.return_value = ({}, [])
        with patch('targets.launch_game') as launch:
            self.step()
            launch.assert_called_once()
        self.assertEqual(self.auto.phase, 'discover')
        self.probe.return_value = ({2: 'game'}, [{'hwnd': 456}])
        self.step()
        self.ui.find_steam.assert_called_once()

    def test_launch_failure_reports_and_stops(self):
        self.auto.start()
        self.probe.return_value = ({}, [])
        with patch('targets.launch_game', side_effect=RuntimeError('missing game')):
            self.step()
        self.assertFalse(self.auto.active)
        self.assertIn('missing game', self.ui.telegram.notify.call_args.args[0])

    def test_unknown_navigation_does_not_start_combat(self):
        self.auto.start()
        self.auto.phase = 'navigation'
        self.ui.siege = SimpleNamespace(active=False, destination=None)
        self.ui.start_endless_bosses = Mock()
        self.step()
        self.ui.start_endless_bosses.assert_not_called()
        self.assertFalse(self.auto.active)

    def test_fresh_video_starts_navigation_even_when_ocr_is_missing_stale_or_failed(self):
        for result in (None, {'received': 0, 'match': None},
                       {'received': time.perf_counter(), 'error': 'OCR unavailable'}):
            with self.subTest(result=result):
                self.ui.siege = None
                self.auto.start()
                self.auto.phase = 'observe'
                self.ui.siege = None
                self.ui.vision.relogin_result = result
                nav = SimpleNamespace(start_navigation=Mock(), active=True)
                with patch('autopilot.SiegeNavigation', return_value=nav):
                    self.step()
                nav.start_navigation.assert_called_once()
                self.assertEqual(self.auto.phase, 'navigation')
                self.auto.stop()

    def test_missing_video_never_starts_navigation(self):
        self.auto.start()
        self.auto.phase = 'observe'
        self.ui.telegram_ready.return_value = False
        with patch('autopilot.SiegeNavigation') as nav:
            self.step()
        nav.assert_not_called()

    def test_fresh_relogin_match_takes_priority_over_navigation(self):
        self.auto.start()
        self.auto.phase = 'observe'
        self.ui.vision.relogin_result = {'received': time.perf_counter(), 'match': {'point': (1, 2)}}
        with patch('autopilot.SiegeNavigation') as nav:
            self.step()
        nav.assert_not_called()
        self.assertTrue(self.ui.relogin_required)
