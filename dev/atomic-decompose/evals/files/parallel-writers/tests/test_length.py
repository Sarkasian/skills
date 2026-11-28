import unittest

from conv import length


class Convert(unittest.TestCase):
    def test_convert(self):
        self.assertAlmostEqual(length.convert(1), 3.28084)
