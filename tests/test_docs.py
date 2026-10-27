from html.parser import HTMLParser
from pathlib import Path
import re
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
        chinese = (ROOT / "README.md").read_text(encoding="utf-8")
        english = (ROOT / "README.en.md").read_text(encoding="utf-8")
        compatibility = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        self.assertIn("**简体中文**", chinese)
        self.assertIn("README.en.md", chinese)
        self.assertIn("[简体中文](README.md)", english)
        self.assertIn("README.en.md", compatibility)

    def test_default_markdown_routes_are_simplified_chinese(self):
        expected = {
            "README.md": "为什么需要它",
            "SKILL.md": "把机械等待移出 Codex 回合",
            "references/acceptance.md": "真实 CLI 验收阶梯",
            "references/codex-support.md": "Codex 支持边界",
            "references/operations.md": "运维说明",
            "references/task-contract.md": "任务契约",
        }
        for relative, marker in expected.items():
            content = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(marker, content, relative)

        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(
            skill.startswith(
                "---\n"
                "name: long-horizon-orchestrator\n"
                "description: Run durable inference/training or other long pipelines"
            )
        )

    def test_local_markdown_links_resolve(self):
        for path in ROOT.rglob("*.md"):
            if ".git" in path.parts:
                continue
            content = path.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^]]*\]\(([^)]+)\)", content):
                target = target.split("#", 1)[0]
                if not target or target.startswith(("http:", "https:")):
                    continue
                resolved = (path.parent / target).resolve()
                self.assertTrue(resolved.exists(), f"missing local target: {path} -> {target}")


if __name__ == "__main__":
    unittest.main()
