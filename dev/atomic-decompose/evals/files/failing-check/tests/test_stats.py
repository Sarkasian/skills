import unittest

import stats


class Mean(unittest.TestCase):
    def test_mean(self):
        self.assertEqual(stats.mean([2, 4]), 3)
