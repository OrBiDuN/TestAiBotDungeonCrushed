import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from launcher import Launcher
from bosssearch import BossSearch, SceneDetector
from build_siege_assets import read_reference

class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_reference_scenes_and_moving_button(self):
        detector = SceneDetector()
        expected = ['Главный экран','Рейтинг осады','Осады — поиск боссов',
                    'Осады — поиск боссов','Меню босса · Атака найдена · На все найдена']
        results = [detector.inspect(read_reference(i)) for i in range(5)]
        self.assertEqual([r['scene'] for r in results], expected)
        self.assertGreater(results[3]['track']['point'][1], results[2]['track']['point'][1])

    def test_search_retargets_then_stops_when_absent(self):
        ui = Launcher()
        route = BossSearch(ui)
        ui.siege = route
        route.active = True
        route.phase = 'find'
        route.hwnd = 123
        route.sent = 0
        route.known_count = 0
        route.scrolls = 0
        route.card_detector = SimpleNamespace(detect=lambda _: [])
        route.previous_point = None
        route.last_sequence = route.sent_sequence = -1
        route.missing_since = None
        route.deadline = 20
        route.area = SimpleNamespace(absolute=lambda point: point)
        frame = SimpleNamespace(sequence=1,image=None)
        route.frame = lambda: frame
        match = {'point': (960,332)}
        route.matcher.find = lambda *_: match
        ui.begin = lambda *args, **kwargs: setattr(ui,'operation',{})
        try:
            with patch('bosssearch.win.user32.GetAsyncKeyState',return_value=0), patch('bosssearch.win.user32.GetForegroundWindow',return_value=123), patch('bosssearch.pixels',lambda image:image), patch('bosssearch.time.monotonic') as now:
                now.return_value = 10
                route.tick()
                self.assertEqual(ui.point,(960,332))
                ui.operation['check_before_click']()
                self.assertEqual(route.sent,1)
                ui.operation = None
                route.tick()
                frame.sequence=2
                now.return_value=10.5
                route.tick()
                self.assertIsNone(ui.operation) # Old location is not clicked again.
                match = {'point':(960,526)}
                frame.sequence=3
                route.tick()
                self.assertEqual(ui.point,(960,526))
                ui.operation['check_before_click']()
                self.assertEqual(route.sent,2)
                ui.operation=None
                route.tick()
                match=None
                now.return_value=11
                frame.sequence=4
                route.tick()
                self.assertTrue(route.active)
                now.return_value=11.7
                frame.sequence=5
                route.tick()
                self.assertFalse(route.active)
                self.assertEqual(route.sent,2)
        finally:
            ui.close()

    def test_endless_mode_reads_one_card_without_scroll_then_requires_new_track(self):
        ui = Launcher(); route = BossSearch(ui); ui.siege = route
        route.active = True; route.open_boss = route.kill_boss = route.endless = True
        route.completed_bosses = 0
        route.sent = route.known_count = 1
        route.area = SimpleNamespace(absolute=lambda point: point)
        route.card_detector = SimpleNamespace(detect=lambda _: [dict(partial=False, attack=(960,416), rect=(700,250,500,200))])
        route.frame = lambda: SimpleNamespace(image=None, sequence=3, received=100)
        route.timer.stop()
        try:
            with patch('bosssearch.pixels',lambda image:image), patch('bosssearch.time.monotonic',return_value=10), patch('bosssearch.time.perf_counter',return_value=20):
                route.finish_search('Найдена одна осада; прекращаю поиск.')
                self.assertEqual(route.phase,'read_boss')
                self.assertFalse(hasattr(route,'scroll_remaining'))
                route.on_combat_finished()
                self.assertEqual(route.phase,'wait_next_track')
                self.assertTrue(route.active)
                route.matcher.find=lambda *_:None
                route.next_track_deadline=9
                with patch('bosssearch.win.user32.GetAsyncKeyState',return_value=0):
                    route.tick()
                self.assertFalse(route.active)
        finally:
            ui.close()

if __name__=='__main__':
    unittest.main()
