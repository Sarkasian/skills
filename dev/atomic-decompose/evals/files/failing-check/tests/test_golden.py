import json
import os
import unittest

import stats

HERE = os.path.dirname(os.path.abspath(__file__))


class Golden(unittest.TestCase):
    def test_mean_matches_the_golden_value(self):
        with open(os.path.join(HERE, '..', 'golden.json')) as f:
            golden = json.load(f)
        self.assertEqual(stats.mean([1, 2, 3, 4]), golden['mean_1_2_3_4'])
