import unittest

from android_agent import safety


class AssessTests(unittest.TestCase):
    def test_plain_text_is_safe(self):
        self.assertFalse(safety.assess("เปิด Settings"))
        self.assertFalse(safety.assess("search for lo-fi music"))

    def test_thai_payment_words(self):
        for text in ["ยืนยันการชำระเงิน", "โอนเงิน 500 บาท", "สั่งซื้อเลย", "ลบข้อมูลทั้งหมด"]:
            with self.subTest(text=text):
                self.assertTrue(safety.assess(text).risky)

    def test_english_payment_words(self):
        for text in ["Pay now", "place order", "CHECKOUT", "Delete account"]:
            with self.subTest(text=text):
                self.assertTrue(safety.assess(text).risky)

    def test_english_word_boundaries(self):
        # "paypal" or "buyer" should not trip the guard.
        self.assertFalse(safety.assess("open paypal history"))
        self.assertFalse(safety.assess("buyer protection policy"))

    def test_empty_text(self):
        self.assertFalse(safety.assess(""))
        self.assertFalse(safety.assess(None))  # type: ignore[arg-type]

    def test_matched_terms_reported(self):
        hit = safety.assess("โอนเงิน")
        self.assertTrue(hit.risky)
        self.assertIn("โอนเงิน", hit.matched)
        self.assertIn("โอนเงิน", hit.reason)


class GoalHeadsUpTests(unittest.TestCase):
    def test_purchase_goal(self):
        self.assertTrue(safety.goal_heads_up("สั่งซื้อหมวกจาก Shopee").risky)

    def test_read_only_goal(self):
        self.assertFalse(safety.goal_heads_up("เปิด Settings ดูเลข Android").risky)


class ShouldAskTests(unittest.TestCase):
    def setUp(self):
        self.risk = safety.assess("ชำระเงิน")
        self.safe = safety.assess("เปิด YouTube")

    def test_risky_mode(self):
        self.assertTrue(safety.should_ask("risky", self.risk))
        self.assertFalse(safety.should_ask("risky", self.safe))

    def test_all_mode(self):
        self.assertTrue(safety.should_ask("all", self.safe))

    def test_none_mode(self):
        self.assertFalse(safety.should_ask("none", self.risk))

    def test_unknown_mode_falls_back_to_risky(self):
        self.assertTrue(safety.should_ask("banana", self.risk))
        self.assertFalse(safety.should_ask("banana", self.safe))


if __name__ == "__main__":
    unittest.main()
