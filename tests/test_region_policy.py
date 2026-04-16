import unittest

from utils.region_policy import is_openai_region_blocked


class RegionPolicyTests(unittest.TestCase):
    def test_hk_is_allowed_but_cn_remains_blocked(self):
        self.assertFalse(is_openai_region_blocked("HK"))
        self.assertTrue(is_openai_region_blocked("CN"))


if __name__ == "__main__":
    unittest.main()
