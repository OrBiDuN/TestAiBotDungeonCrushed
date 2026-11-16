import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from telegram_control import TelegramRemote, TelegramAPI


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.remote = TelegramRemote(self.temp.name, api=Mock())
        self.remote.started_at = time.time() - 2
        self.index = 0

    def message(self, text, user=10, chat=10, age=0, kind='private'):
        self.index += 1
        return {'update_id': self.index, 'message': {
            'from': {'id': user}, 'chat': {'id': chat, 'type': kind},
            'date': int(time.time()) - age, 'text': text}}

    def pair(self):
        self.remote.accept(self.message('/pair ' + self.remote.code))
        if self.remote.owner:
            self.assertEqual(self.remote.next_command(), 'menu')

    def test_pairing_requires_secret_and_private_chat(self):
        self.remote.accept(self.message('/start'))
        self.remote.accept(self.message('Привет'))
        self.remote.accept(self.message('/pair wrong'))
        self.remote.accept(self.message('/pair ' + self.remote.code, kind='group'))
        self.assertIsNone(self.remote.owner)
        self.pair()
        self.assertEqual(self.remote.owner, {'user': 10, 'chat': 10})
        self.assertEqual(json.loads(self.remote.owner_path.read_text()), self.remote.owner)

    def test_expired_pairing_rejected(self):
        self.remote.code_expires = 0
        self.pair()
        self.assertIsNone(self.remote.owner)

    def test_unauthorized_and_stale_and_duplicate_commands(self):
        self.pair()
        for options in ({'user': 11}, {'chat': 11}, {'age': 60}, {'kind': 'group'}):
            self.remote.accept(self.message('/run', **options))
        self.assertIsNone(self.remote.next_command())
        update = self.message('/run')
        self.remote.accept(update)
        self.remote.accept(update)
        self.assertEqual(self.remote.next_command(), 'run')
        self.assertIsNone(self.remote.next_command())

    def test_stop_clears_pending_runs_even_when_queue_full(self):
        self.pair()
        for _ in range(30):
            self.remote.accept(self.message('/run'))
        self.remote.accept(self.message('/stop'))
        self.remote.accept(self.message('/run'))
        self.assertEqual(self.remote.next_command(), 'stop')
        self.assertIsNone(self.remote.next_command())

    def test_aged_local_command_expires(self):
        self.remote.commands.put(('run', time.monotonic() - 20))
        self.assertIsNone(self.remote.next_command())

    def test_unknown_text_and_media_open_menu_every_time(self):
        self.pair()
        for text in ('Привет', '???', '', '/unknown'):
            self.remote.accept(self.message(text))
            self.assertEqual(self.remote.next_command(), 'menu')
        self.remote.accept(self.message('Привет', user=99))
        self.assertIsNone(self.remote.next_command())

    def test_setup_buttons_and_custom_keyboard(self):
        from telegram_control import SETUP_MENU
        self.pair()
        for text, expected in [('🔎 Найти игру', 'find'), ('🔄 Подготовить область', 'setup')]:
            self.remote.accept(self.message(text))
            self.assertEqual(self.remote.next_command(), expected)
        self.remote.notify('Подготовка', menu=SETUP_MENU)
        payload = None
        while not self.remote.outgoing.empty():
            payload = self.remote.outgoing.get_nowait()[0]
        self.assertEqual(payload['reply_markup'], SETUP_MENU)

    def test_secret_not_in_network_exception(self):
        with patch('urllib.request.urlopen', side_effect=OSError('secret-token')):
            with self.assertRaisesRegex(RuntimeError, '^Нет ответа Telegram$'):
                TelegramAPI('secret-token').call('getMe', {})


class LauncherRemoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from launcher import Launcher
        self.ui = Launcher()
        self.remote = Mock()
        self.remote.owner = {'user': 10, 'chat': 10}
        self.remote.connected = True
        self.remote.last_contact = time.monotonic()
        self.ui.telegram = self.remote
        self.ui.telegram_menu_checked = time.monotonic()
        self.addCleanup(self.ui.close)

    def test_stop_keeps_capture_and_releases_input(self):
        self.remote.next_command.return_value = 'stop'
        self.ui.held = True
        self.ui.operation = {'phase': 'release'}
        with patch('launcher.win.send') as send, patch.object(self.ui, 'stop_live') as stop_live:
            self.ui.poll_telegram()
            self.assertIsNone(self.ui.operation)
            self.assertFalse(self.ui.held)
            send.assert_called_once_with(0x0004)
            stop_live.assert_not_called()

    def test_screen_does_not_cancel_route(self):
        from types import SimpleNamespace
        from PySide6.QtGui import QImage
        self.remote.next_command.return_value = 'screen'
        frame = SimpleNamespace(image=QImage(20, 20, QImage.Format_RGB32),
                                received=time.perf_counter(), wall_time=time.time())
        with patch.object(self.ui, 'latest_video_frame', return_value=frame), patch.object(self.ui, 'cancel') as cancel:
            self.ui.poll_telegram()
            cancel.assert_not_called()
        self.assertTrue(self.remote.notify.call_args.kwargs['photo'].startswith(b'\xff\xd8'))

    def test_stale_screen_rejected(self):
        self.remote.next_command.return_value = 'screen'
        self.ui.poll_telegram()
        self.assertIn('Нет свежего', self.remote.notify.call_args.args[0])

    def test_duplicate_run_does_not_restart_active_route(self):
        self.ui.siege = Mock(active=True)
        self.remote.next_command.return_value = 'run'
        with patch.object(self.ui, 'start_endless_bosses') as start:
            self.ui.poll_telegram()
            start.assert_not_called()

    def test_start_shows_mode_choice(self):
        self.remote.next_command.return_value = 'run'
        with patch.object(self.ui, 'start_endless_bosses') as start, patch.object(self.ui, 'telegram_ready', return_value=True):
            self.ui.poll_telegram()
            start.assert_not_called()
        from telegram_control import MODE_MENU
        self.assertEqual(self.remote.notify.call_args.kwargs['menu'], MODE_MENU)

    def test_unready_run_shows_modes_without_manual_setup(self):
        from telegram_control import MODE_MENU
        self.remote.next_command.return_value = 'run'
        with patch.object(self.ui, 'start_endless_bosses') as start:
            self.ui.poll_telegram()
            start.assert_not_called()
        self.assertEqual(self.remote.notify.call_args.kwargs['menu'], MODE_MENU)

    def test_idle_menu_does_not_require_manual_setup(self):
        from telegram_control import MENU
        for ready in (False, True, False):
            with patch.object(self.ui, 'telegram_ready', return_value=ready):
                self.ui.show_telegram_menu(True)
            self.assertEqual(self.remote.notify.call_args.kwargs['menu'], MENU)

    def test_endless_choice_starts_automatic_preparation(self):
        self.remote.next_command.return_value = 'endless'
        self.ui.poll_telegram()
        self.assertTrue(self.ui.autopilot.active)
        self.assertEqual(self.ui.autopilot.phase, 'discover')
        self.remote.next_command.return_value = 'stop'
        self.ui.poll_telegram()
        self.assertFalse(self.ui.autopilot.active)

    def test_setup_waits_for_wake_capture_shutdown_and_fresh_frame(self):
        from telegram_control import MENU
        action = Mock()
        def find():
            self.ui.pending_activation = {'action': action}
            return True
        with patch.object(self.ui, 'find_steam', side_effect=find), patch.object(self.ui, 'start_live') as start, patch.object(self.ui, 'telegram_ready', return_value=False) as ready:
            self.ui.prepare_telegram_game(True)
            self.ui.advance_telegram_setup()
            start.assert_not_called()
            self.ui.pending_activation['action']()
            action.assert_called_once()
            self.ui.pending_activation = None
            self.ui.live = Mock()
            self.ui.live.isRunning.return_value = True
            self.ui.advance_telegram_setup()
            start.assert_not_called()
            self.ui.live.isRunning.return_value = False
            self.ui.advance_telegram_setup()
            start.assert_called_once()
            self.ui.advance_telegram_setup()
            self.assertIsNotNone(self.ui.telegram_setup)
            ready.return_value = True
            self.ui.advance_telegram_setup()
            self.assertIsNone(self.ui.telegram_setup)
            self.assertEqual(self.remote.notify.call_args.kwargs['menu'], MENU)
        self.ui.live = None

    def test_stop_cancels_setup_and_pending_wake(self):
        self.ui.telegram_setup = {'phase': 'wake', 'deadline': time.monotonic() + 10}
        self.ui.pending_activation = {'action': Mock()}
        self.remote.next_command.return_value = 'stop'
        self.ui.poll_telegram()
        self.assertIsNone(self.ui.telegram_setup)
        self.assertIsNone(self.ui.pending_activation)

    def test_setup_does_not_interrupt_running_route(self):
        self.ui.siege = Mock(active=True)
        with patch.object(self.ui, 'find_steam') as find:
            self.ui.prepare_telegram_game(True)
            find.assert_not_called()

    def test_setup_missing_game_and_timeout_return_setup_menu(self):
        from telegram_control import MENU
        with patch.object(self.ui, 'find_steam', return_value=False):
            self.ui.prepare_telegram_game(True)
        self.assertIsNone(self.ui.telegram_setup)
        self.assertEqual(self.remote.notify.call_args.kwargs['menu'], MENU)
        self.ui.telegram_setup = {'phase': 'wake', 'deadline': time.monotonic() - 1}
        self.ui.advance_telegram_setup()
        self.assertIsNone(self.ui.telegram_setup)
        self.assertEqual(self.remote.notify.call_args.kwargs['menu'], MENU)

    def test_disconnect_keeps_autonomous_route_running(self):
        route = Mock(active=True)
        route.cancel.side_effect = lambda: setattr(route, 'active', False)
        self.ui.siege = route
        self.remote.next_command.return_value = None
        self.remote.last_contact = time.monotonic() - 61
        self.ui.poll_telegram()
        route.cancel.assert_not_called()
        self.assertTrue(route.active)


if __name__ == '__main__':
    unittest.main()
