"""Validation tests for the 50-story Bali Ten adaptation bank."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from story_repository import StoryDatabase  # noqa: E402


STORY_BANK = ROOT / "backend" / "stories_bali_50.json"


def is_binary_suggestion(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text)
    if re.match(r"^是/?不是", normalized):
        return True
    if re.match(
        r"^(为什么|为何|怎么|如何|谁|什么|哪里|哪儿|多少|多久|哪一)",
        normalized,
    ):
        return False
    if re.search(
        r"(为什么|为何|怎么|如何|谁|哪里|哪儿|多少|多久|哪一)",
        normalized,
    ):
        return False
    if re.search(
        r"(是否|是不是|有没有|会不会|能不能|可不可以|对不对|算不算)",
        normalized,
    ) or re.search(r"[吗？?]$", normalized):
        return True
    return "什么" not in normalized


class BaliStoryBankTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(STORY_BANK.read_text(encoding="utf-8"))
        cls.stories = cls.payload["stories"]

    def test_bank_loads_all_fifty_unique_stories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = StoryDatabase(
                STORY_BANK,
                Path(temp_dir) / "bali.db",
            )
            database.initialize()
            self.assertEqual(
                len(database.get_judge_story("bali-001")["suggestions"]),
                3,
            )
            reveal = database.get_reveal("bali-001")
            self.assertTrue(reveal["summary"])
            self.assertLessEqual(len(reveal["summary"]), 180)
            self.assertNotEqual(reveal["summary"], reveal["bottom"])

        self.assertEqual(database.story_count, 50)
        self.assertEqual(len(self.stories), 50)
        self.assertEqual(
            len({story["id"] for story in self.stories}),
            50,
        )

    def test_every_story_has_web_schema_material(self) -> None:
        for story in self.stories:
            with self.subTest(story=story["id"]):
                self.assertTrue(story["surface"])
                self.assertTrue(story["summary"])
                self.assertLessEqual(len(story["summary"]), 180)
                self.assertTrue(story["bottom"])
                self.assertEqual(len(story["facts"]), 5)
                self.assertEqual(len(story["hints"]), 2)
                self.assertEqual(len(story["suggestions"]), 3)
                self.assertEqual(
                    len({fact["id"] for fact in story["facts"]}),
                    5,
                )
                self.assertGreaterEqual(
                    sum(1 for fact in story["facts"] if fact["truth"]),
                    3,
                )
                self.assertTrue(
                    all(
                        fact["aliases"] and fact.get("evidence")
                        for fact in story["facts"]
                    )
                )

    def test_suggestions_are_binary(self) -> None:
        for story in self.stories:
            for suggestion in story["suggestions"]:
                with self.subTest(
                    story=story["id"],
                    suggestion=suggestion,
                ):
                    self.assertTrue(is_binary_suggestion(suggestion))

    def test_source_and_review_metadata_are_present(self) -> None:
        dataset = self.payload["dataset"]

        self.assertEqual(dataset["source_author"], "八里十")
        self.assertIn("授权", dataset["rights_status"])
        self.assertEqual(dataset["review_status"], "needs_human_review")
        for story in self.stories:
            self.assertEqual(story["source_author"], "八里十")
            self.assertEqual(story["review_status"], "needs_human_review")

    def test_no_ocr_replacement_character_remains(self) -> None:
        for story in self.stories:
            content = (
                story["surface"]
                + story["bottom"]
                + "".join(story["hints"])
                + "".join(story["suggestions"])
            )
            with self.subTest(story=story["id"]):
                self.assertNotIn("�", content)


if __name__ == "__main__":
    unittest.main()
