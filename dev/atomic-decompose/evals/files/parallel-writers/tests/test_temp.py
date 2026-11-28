import unittest

from conv import temp


class Convert(unittest.TestCase):
    def test_convert(self):
        self.assertAlmostEqual(temp.convert(100), 212)
