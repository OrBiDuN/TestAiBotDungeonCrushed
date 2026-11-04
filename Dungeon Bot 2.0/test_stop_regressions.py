"""Cancellation regression: no real mouse or keyboard input is sent."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from launcher import Launcher
from bosssearch import BossSearch


class StopRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_escape_interrupts_scroll_at_start_middle_and_end(self):
        for direction in (-1, 1):
            for completed in (1, 50, 99):
                with self.subTest(direction=direction, completed=completed):
                    ui = Launcher()
                    route = BossSearch(ui)
                    ui.siege = route
                    route.active = True
                    route.phase = 'scroll_burst'
                    route.scroll_direction = direction
                    route.scroll_remaining = 100
                    route.frame = lambda: SimpleNamespace(sequence=1)
                    ui.point = (960, 550)
                    ui.validate_target = lambda: None
                    try:
                        with patch('bosssearch.win.user32.GetAsyncKeyState', return_value=0) as key, patch('bosssearch.scroll_step') as wheel, patch('bosssearch.win.position', return_value=ui.point):
                            for _ in range(completed):
                                route.tick()
                            self.assertEqual(wheel.call_count, completed)
                            key.return_value = 0x8000
                            route.tick()
                            self.assertFalse(route.active)
                            self.assertFalse(route.timer.isActive())
                            for _ in range(110):
                                route.tick()
                            self.assertEqual(wheel.call_count, completed)
                            self.assertIsNone(ui.operation)
                    finally:
                        ui.close()

    def test_stop_cancels_pending_phases_and_releases_held_button(self):
        phases = ('wake', 'moving', 'pause', 'release')
        for phase in phases:
            with self.subTest(phase=phase):
                ui = Launcher()
                route = BossSearch(ui)
                ui.siege = route
                route.active = True
                route.phase = 'boss_click'
                ui.operation = {'phase': phase}
                ui.pending_activation = {'action': lambda: self.fail('Cancelled activation ran')}
                ui.held = phase == 'release'
                try:
                    with patch('launcher.win.send') as send, patch('launcher.win.move') as move:
                        ui.stop()
                        self.assertFalse(route.active)
                        self.assertIsNone(ui.operation)
                        self.assertIsNone(ui.pending_activation)
                        self.assertFalse(ui.held)
                        ui.advance()
                        route.tick()
                        move.assert_not_called()
                        if phase == 'release':
                            send.assert_called_once_with(0x0004)
                        else:
                            send.assert_not_called()
                finally:
                    ui.close()

if __name__ == '__main__':
    unittest.main()
