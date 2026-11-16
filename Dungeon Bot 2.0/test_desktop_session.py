import unittest
from unittest.mock import patch, Mock
import time
import desktop_session as desktop


class DesktopTests(unittest.TestCase):
    def info(self, state=4, console=2):
        return {'session': 1, 'console': console, 'state': state, 'foreground': None}

    def test_active_session_is_not_switched(self):
        with patch.object(desktop, 'snapshot', return_value=self.info(0)), patch.object(desktop.wts, 'WTSConnectSessionW') as connect:
            self.assertFalse(desktop.request_restore())
            connect.assert_not_called()

    def test_only_own_disconnected_session_to_empty_console(self):
        with patch.object(desktop, 'snapshot', return_value=self.info()), patch.object(desktop, 'query', return_value=''), patch.object(desktop.wts, 'WTSConnectSessionW', return_value=True) as connect:
            self.assertTrue(desktop.request_restore())
            connect.assert_called_once_with(1, 2, '', False)

    def test_occupied_console_is_not_displaced(self):
        with patch.object(desktop, 'snapshot', return_value=self.info()), patch.object(desktop, 'query', return_value='another-user'), patch.object(desktop.wts, 'WTSConnectSessionW') as connect:
            with self.assertRaisesRegex(RuntimeError, 'занят'):
                desktop.request_restore()
            connect.assert_not_called()

    def test_invalid_console_is_rejected(self):
        for console in (1, 0xffffffff):
            with patch.object(desktop, 'snapshot', return_value=self.info(console=console)):
                with self.assertRaises(RuntimeError):
                    desktop.request_restore()

    def test_denied_access_explains_admin_requirement(self):
        with patch.object(desktop, 'snapshot', return_value=self.info()), patch.object(desktop, 'query', return_value=''), patch.object(desktop.wts, 'WTSConnectSessionW', return_value=False), patch.object(desktop.C, 'get_last_error', return_value=5):
            with self.assertRaisesRegex(RuntimeError, 'администратора'):
                desktop.request_restore()

    def test_launcher_checks_completion_and_timeout(self):
        from PySide6.QtWidgets import QApplication
        from launcher import Launcher
        app = QApplication.instance() or QApplication([])
        ui = Launcher()
        ui.telegram = Mock()
        try:
            ui.desktop_restore_deadline = time.monotonic()+20
            with patch.object(desktop, 'snapshot', return_value=self.info()):
                ui.poll_desktop_restore()
            self.assertIsNotNone(ui.desktop_restore_deadline)
            info = self.info(0, 1)
            info['foreground'] = 123
            with patch.object(desktop, 'snapshot', return_value=info):
                ui.poll_desktop_restore()
            self.assertIsNone(ui.desktop_restore_deadline)
            self.assertIn('/setup', ui.telegram.notify.call_args.args[0])
            ui.desktop_restore_deadline = time.monotonic()-1
            with patch.object(desktop, 'snapshot', return_value=self.info()):
                ui.poll_desktop_restore()
            self.assertIsNone(ui.desktop_restore_deadline)
            self.assertIn('не подтверждено', ui.telegram.notify.call_args.args[0])
        finally:
            ui.close()


if __name__ == '__main__':
    unittest.main()
