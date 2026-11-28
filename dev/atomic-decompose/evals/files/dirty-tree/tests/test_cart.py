import unittest

from shop import cart


class Count(unittest.TestCase):
    def test_count(self):
        self.assertEqual(cart.count([(10.0, 2), (5.0, 1)]), 3)
