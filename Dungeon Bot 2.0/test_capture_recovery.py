import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch, Mock
from livecapture import LiveCapture
from siege import SiegeRoute


class FakeStop:
    def __init__(self, clock, until):
        self.clock, self.until, self.stopped = clock, until, False
    def is_set(self): return self.stopped
    def set(self): self.stopped = True
    def wait(self, delay):
        self.clock[0] += delay
        if self.clock[0] >= self.until: self.set()
        return self.stopped


class CaptureRecoveryTests(unittest.TestCase):
    def simulate(self, kinds, until=60, count=0):
        clock, sessions = [100.0], []
        with patch('livecapture.win.identity', return_value=(1, 2)):
            live = LiveCapture(123)
        live._count = count
        live._stop = FakeStop(clock, 100+until)
        def factory(**kwargs):
            capture = NS()
            kind = kinds[min(len(sessions), len(kinds)-1)]
            sessions.append(capture)
            def start():
                if kind == 'error': raise RuntimeError('device lost')
                def finished():
                    if kind == 'frames':
                        live._count += 1
                        live._last = clock[0]
                    if kind == 'closed': capture.closed_handler()
                    return kind == 'finished'
                def stop():
                    capture.closed_handler()
                    capture.frame_handler(None, NS(stop=lambda: None))
                return NS(is_finished=finished, wait=lambda: None, stop=stop)
            capture.start_free_threaded = start
            return capture
        with patch('livecapture.win.identity', return_value=(1, 2)), \
             patch('livecapture.win.user32.IsIconic', return_value=False), \
             patch('livecapture.time.perf_counter', side_effect=lambda: clock[0]), \
             patch('windows_capture.WindowsCapture', side_effect=factory):
            live.run()
        self.assertIsNone(live.snapshot()['error'])
        return live, sessions

    def test_first_frame_timeout_uses_session_not_lifetime_count(self):
        live, sessions = self.simulate(['silent'], 40, count=100)
        self.assertGreaterEqual(len(sessions), 4)

    def test_retries_beyond_three(self):
        live, sessions = self.simulate(['closed'], 65)
        self.assertGreater(len(sessions), 3)
        self.assertIsNone(live.latest_frame())

    def test_native_start_failure_recovers(self):
        live, sessions = self.simulate(['error', 'frames'], 15)
        self.assertEqual(len(sessions), 2)
        self.assertGreater(live.snapshot()['count'], 0)

    def test_unexpected_finish_recovers(self):
        live, sessions = self.simulate(['finished', 'frames'], 15)
        self.assertEqual(len(sessions), 2)

    def test_manual_stop_during_backoff(self):
        live, sessions = self.simulate(['closed'], .5)
        self.assertEqual(len(sessions), 1)

    def test_changed_window_is_terminal(self):
        with patch('livecapture.win.identity', return_value=(1, 2)):
            live = LiveCapture(123)
        with patch('livecapture.win.identity', return_value=(3, 4)), \
             patch('windows_capture.WindowsCapture') as factory:
            live.run()
        factory.assert_not_called()
        self.assertIsNotNone(live.snapshot()['error'])

    def test_route_wait_preserves_phase_and_extends_deadline(self):
        live = NS(isRunning=lambda: True, snapshot=lambda: {'error': None}, latest_frame=lambda: None)
        route = NS(live=live, ui=NS(live=live), phase='confirm',
                   deadline=15., attempts={'normal'}, log=Mock())
        with patch('siege.time.monotonic', return_value=10.):
            self.assertTrue(SiegeRoute.wait_for_video(route))
        live.latest_frame = lambda: NS(received=20.)
        with patch('siege.time.monotonic', return_value=20.), patch('siege.time.perf_counter', return_value=20.):
            self.assertFalse(SiegeRoute.wait_for_video(route))
        self.assertEqual(route.deadline, 25.)
        self.assertEqual(route.phase, 'confirm')
        self.assertEqual(route.attempts, {'normal'})

    def test_pending_input_waits_but_mouse_up_is_never_delayed(self):
        from PySide6.QtWidgets import QApplication
        from launcher import Launcher
        app = QApplication.instance() or QApplication([])
        ui = Launcher()
        route = NS(active=True, wait_for_video=Mock(return_value=True), cancel=lambda: None)
        ui.siege = route
        ui.validate_target = lambda: None
        ui.point = (100, 100)
        check = Mock()
        try:
            with patch('launcher.win.user32.GetAsyncKeyState', return_value=0), \
                 patch('launcher.win.move') as move, patch('launcher.win.send') as send:
                for phase in ('moving', 'pause'):
                    ui.operation = dict(phase=phase, due=0, check_before_click=check)
                    ui.advance()
                    self.assertEqual(ui.operation['phase'], phase)
                check.assert_not_called()
                move.assert_not_called()
                send.assert_not_called()
                ui.held = True
                ui.operation = dict(phase='release', due=0, check_before_click=check)
                ui.advance()
                send.assert_called_once_with(0x0004)
                self.assertFalse(ui.held)
                self.assertIsNone(ui.operation)
        finally:
            ui.siege = None
            ui.close()

if __name__ == '__main__': unittest.main()
