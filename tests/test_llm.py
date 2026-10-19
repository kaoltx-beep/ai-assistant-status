import unittest

from android_agent.llm import LlmError, extract_json


class ExtractJsonTests(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})

    def test_fenced_json(self):
        self.assertEqual(extract_json('```json\n{"a": 2}\n```'), {"a": 2})

    def test_fenced_without_language(self):
        self.assertEqual(extract_json('```\n{"a": 3}\n```'), {"a": 3})

    def test_json_with_prose_around_it(self):
        text = 'Sure! Here is the action:\n{"tool": "tap", "args": {"x": 1}}\nhope it helps'
        self.assertEqual(extract_json(text)["tool"], "tap")

    def test_thai_values_survive(self):
        self.assertEqual(extract_json('{"summary": "เปิดแอปแล้ว"}')["summary"], "เปิดแอปแล้ว")

    def test_garbage_raises(self):
        with self.assertRaises(LlmError):
            extract_json("I cannot do that")

    def test_malformed_raises(self):
        with self.assertRaises(LlmError):
            extract_json('{"a": }')


if __name__ == "__main__":
    unittest.main()
