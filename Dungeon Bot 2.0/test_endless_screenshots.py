import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtGui import QImage
from siege import SiegeRoute


class ScreenshotTests(unittest.TestCase):
    def test_full_png_deduplication_and_next_boss(self):
        image = QImage(1920, 1080, QImage.Format_RGB32)
        image.fill(0xff123456)
        frame = SimpleNamespace(image=image, sequence=12)
        route = SimpleNamespace(endless=True, completed_bosses=0, run_id='test', log=Mock())
        with tempfile.TemporaryDirectory() as directory, patch('siege.ROOT', Path(directory)):
            for stage in ('found', 'menu', 'finished', 'found'):
                SiegeRoute.save_endless_frame(route, frame, stage)
            route.completed_bosses = 1
            SiegeRoute.save_endless_frame(route, frame, 'found')
            files = list(Path(directory).rglob('*.png'))
            self.assertEqual(len(files), 4)
            for path in files:
                restored = QImage(str(path))
                self.assertEqual(restored.size(), image.size())
                self.assertEqual(restored.pixel(100, 100), image.pixel(100, 100))
            route.endless = False
            SiegeRoute.save_endless_frame(route, frame, 'menu')
            self.assertEqual(len(list(Path(directory).rglob('*.png'))), 4)

    def test_save_failure_is_reported_without_marking_success(self):
        route = SimpleNamespace(endless=True, run_id='test', log=Mock())
        frame = SimpleNamespace(image=Mock(), sequence=1)
        frame.image.save.return_value = False
        with tempfile.TemporaryDirectory() as directory, patch('siege.ROOT', Path(directory)):
            SiegeRoute.save_endless_frame(route, frame, 'found')
        self.assertFalse(getattr(route, '_archived_frames', set()))
        self.assertIn('Не удалось сохранить', route.log.call_args.args[0])
