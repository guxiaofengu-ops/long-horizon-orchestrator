from html.parser import HTMLParser
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.attrs = []

    def handle_starttag(self, tag, attrs):
        self.attrs.append((tag, dict(attrs)))


class DocumentationTests(unittest.TestCase):
    def parse(self, relative):
        path = ROOT / relative
        page = Page()
        page.feed(path.read_text(encoding="utf-8"))
        return path, page

    def test_language_routes_and_local_assets(self):
        for relative, expected_lang in (("docs/index.html", "en"), ("docs/zh/index.html", "zh-CN")):
            path, page = self.parse(relative)
            html = next(attrs for tag, attrs in page.attrs if tag == "html")
            self.assertEqual(html.get("lang"), expected_lang)
            alternates = {
                attrs.get("hreflang")
                for tag, attrs in page.attrs
                if tag == "link" and attrs.get("rel") == "alternate"
            }
            self.assertTrue({"en", "zh-CN", "x-default"}.issubset(alternates))
            for tag, attrs in page.attrs:
                for key in ("href", "src"):
                    value = attrs.get(key, "")
                    if not value or value.startswith(("http:", "https:", "#")):
                        continue
                    target = (path.parent / value.split("#")[0]).resolve()
                    self.assertTrue(target.exists(), f"missing local target: {relative} -> {value}")

    def test_readme_language_switches(self):
        english = (ROOT / "README.md").read_text(encoding="utf-8")
        chinese = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        self.assertIn("README.zh-CN.md", english)
        self.assertIn("README.md", chinese)


if __name__ == "__main__":
    unittest.main()
