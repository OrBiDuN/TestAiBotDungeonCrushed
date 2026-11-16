import unittest
from pathlib import Path
import cv2
import numpy as np
from siege import ButtonMatcher

class PopupMatcherTests(unittest.TestCase):
    def test_user_photo_and_shifted_popup(self):
        source=cv2.imdecode(np.fromfile(Path(__file__).parent/'tests/fixtures/attack_failed_popup.png',np.uint8),cv2.IMREAD_COLOR)
        matcher=ButtonMatcher()
        for offset in (600,625,650):
            frame=np.zeros((1080,1920,3),np.uint8)
            frame[:source.shape[0],offset:offset+source.shape[1]]=source
            hit=matcher.find(frame,'attack_failed_ok')
            self.assertIsNotNone(hit)
            self.assertLessEqual(abs(hit['point'][0]-(offset+335)),2)
            self.assertLessEqual(abs(hit['point'][1]-597),2)
            # A red OK without the specific error text must not be enough.
            frame[455:535,offset+130:offset+540]=0
            self.assertIsNone(matcher.find(frame,'attack_failed_ok'))

    def test_existing_game_screens_do_not_match(self):
        from build_siege_assets import read_reference
        matcher=ButtonMatcher()
        for index in range(6):
            self.assertIsNone(matcher.find(read_reference(index),'attack_failed_ok'))
