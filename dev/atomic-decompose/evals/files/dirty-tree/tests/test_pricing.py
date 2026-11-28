import unittest

from shop import pricing


class Net(unittest.TestCase):
    def test_net(self):
        self.assertEqual(pricing.net(119), 100.0)
