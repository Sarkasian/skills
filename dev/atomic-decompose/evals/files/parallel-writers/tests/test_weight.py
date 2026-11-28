import unittest

from conv import weight


class Convert(unittest.TestCase):
    def test_convert(self):
        self.assertAlmostEqual(weight.convert(1), 2.20462)
