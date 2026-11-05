import unittest

from pkg.cart import cart_total
from pkg.pricing import calc_total


class T(unittest.TestCase):
    def test_calc_total(self):
        self.assertEqual(calc_total([10, 20], 0.1), 33.0)

    def test_cart(self):
        self.assertEqual(cart_total([{"price": 5}]), 6.0)


if __name__ == "__main__":
    unittest.main()
