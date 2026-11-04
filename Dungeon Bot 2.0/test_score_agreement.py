import unittest
from bossocr import agree_points

class ScoreAgreementTests(unittest.TestCase):
    def test_lost_leading_digit_is_not_accepted(self):
        self.assertIsNone(agree_points(['125','1125','1125','']))
        self.assertIsNone(agree_points(['785','1785','1785','1785']))

    def test_agreement_with_blank_variants(self):
        self.assertEqual(agree_points(['2445','2445','','']),2445)
        self.assertEqual(agree_points(['','2445','','']),2445)

    def test_do_not_extract_digits_from_noise(self):
        for readings in (['очки: 125','abc125'],['12 25'],['0'],[''],['-125']):
            self.assertIsNone(agree_points(readings))

if __name__=='__main__':unittest.main()
