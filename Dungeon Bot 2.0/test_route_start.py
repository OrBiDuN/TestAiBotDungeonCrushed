"""Regression: duplicate starts preserve the route and pending input, no native actions."""
import unittest
from PySide6.QtWidgets import QApplication
from launcher import Launcher

class RouteStartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_duplicate_start_preserves_route_and_stop_unlocks_buttons(self):
        ui = Launcher()
        try:
            route = ui.get_siege()
            route.active = True
            route.run_id = 'duplicate-start-regression'
            route.phase = 'wake'
            route.index = 2
            route.limit = 5
            route.attempts = {'home', 'ranking'}
            route.timer.start()
            ui.set_route_running(True)
            operation = {'phase': 'wake'}
            ui.operation = operation
            for navigation_only in (True, False, False):
                ui.guard(lambda: ui.start_siege(navigation_only))
                self.assertTrue(route.active)
                self.assertTrue(route.timer.isActive())
                self.assertIs(ui.operation, operation)
                self.assertEqual((route.phase, route.index, route.limit), ('wake', 2, 5))
                self.assertEqual(route.attempts, {'home', 'ranking'})
                self.assertTrue(all(not b.isEnabled() for b in ui.route_buttons))
            self.assertNotIn('ОШИБКА', ui.log.toPlainText())
            ui.stop()
            self.assertFalse(route.active)
            self.assertFalse(route.timer.isActive())
            self.assertIsNone(ui.operation)
            self.assertTrue(all(b.isEnabled() for b in ui.route_buttons))
        finally:
            ui.close()

if __name__ == '__main__':
    unittest.main()
