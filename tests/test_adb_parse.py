import unittest

from android_agent.adb import UiElement, parse_ui_xml

SAMPLE = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy rotation="0">
  <node text="" content-desc="" clickable="false" bounds="[0,0][1080,2400]">
    <node text="Search" content-desc="" resource-id="com.app:id/search"
          clickable="true" bounds="[40,100][300,160]" />
    <node text="" content-desc="Settings" resource-id="com.app:id/gear"
          clickable="true" bounds="[900,100][1040,160]" />
    <node text="" content-desc="" resource-id="com.app:id/empty"
          clickable="false" bounds="[0,0][10,10]" />
    <node text="Search" content-desc="" resource-id="com.app:id/dup"
          clickable="true" bounds="[40,100][300,160]" />
  </node>
</hierarchy>"""


class ParseUiXmlTests(unittest.TestCase):
    def test_extracts_labelled_elements(self):
        elements = parse_ui_xml(SAMPLE)
        labels = [e.label() for e in elements]
        self.assertIn("Search", labels)
        self.assertIn("Settings", labels)

    def test_skips_unlabelled_and_duplicate(self):
        elements = parse_ui_xml(SAMPLE)
        self.assertEqual(len([e for e in elements if e.label() == "Search"]), 1)
        self.assertNotIn("empty", [e.label() for e in elements])

    def test_bounds_and_center(self):
        elements = parse_ui_xml(SAMPLE)
        gear = next(e for e in elements if e.label() == "Settings")
        self.assertEqual(gear.bounds, (900, 100, 1040, 160))
        self.assertEqual(gear.center, (970, 130))
        self.assertTrue(gear.clickable)

    def test_tappable_first(self):
        elements = parse_ui_xml(SAMPLE)
        self.assertTrue(elements[0].clickable)

    def test_garbage_input(self):
        self.assertEqual(parse_ui_xml(""), [])
        self.assertEqual(parse_ui_xml("ERROR: could not get idle state"), [])
        self.assertEqual(parse_ui_xml("<hierarchy><node"), [])

    def test_limit(self):
        many = ["<node text='x%d' bounds='[0,%d][10,%d]' clickable='true'/>" % (i, i, i)
                for i in range(200)]
        xml = "<hierarchy>" + "".join(many) + "</hierarchy>"
        self.assertEqual(len(parse_ui_xml(xml, limit=80)), 80)


class DescribeTests(unittest.TestCase):
    def test_describe_contains_label_and_coords(self):
        el = UiElement("OK", "", "", (10, 20, 30, 40), True)
        text = el.describe(index=3)
        self.assertIn("[3]", text)
        self.assertIn('"OK"', text)
        self.assertIn("(20,30)", text)
        self.assertIn("tappable", text)


if __name__ == "__main__":
    unittest.main()
