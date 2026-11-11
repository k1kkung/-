"""Validation tests for the custom horror story bank."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from story_repository import StoryDatabase  # noqa: E402


STORY_BANK = ROOT / "backend" / "stories_horror_v1.json"
EXPECTED_IDS = {
    "fifth-staircase",
    "writer-hidden-camera",
    "medical-party-game",
    "twenty-five-point-five",
    "death-age-carpool",
    "novel-page-turner",
    "storage-room-exit",
    "lights-out-stairs",
    "photo-swap-photo",
}


class HorrorStoryBankTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(STORY_BANK.read_text(encoding="utf-8"))
        cls.stories = {
            story["id"]: story for story in cls.payload["stories"]
        }

    def test_bank_loads_through_application_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = StoryDatabase(
                STORY_BANK,
                Path(temp_dir) / "stories.db",
            )
            database.initialize()

        self.assertEqual(database.story_count, len(EXPECTED_IDS))
        self.assertEqual(set(self.stories), EXPECTED_IDS)

    def test_every_story_has_complete_judge_material(self) -> None:
        for story_id, story in self.stories.items():
            with self.subTest(story=story_id):
                self.assertGreaterEqual(len(story["facts"]), 5)
                self.assertGreaterEqual(len(story["hints"]), 2)
                self.assertEqual(len(story["suggestions"]), 3)

    def test_all_suggestions_are_binary_questions(self) -> None:
        open_markers = (
            "为什么",
            "为何",
            "怎么",
            "如何",
            "谁",
            "什么",
            "哪里",
            "哪儿",
            "多少",
            "多久",
            "哪一",
        )
        for story_id, story in self.stories.items():
            for suggestion in story["suggestions"]:
                with self.subTest(story=story_id, suggestion=suggestion):
                    self.assertFalse(
                        any(marker in suggestion for marker in open_markers)
                    )
                    self.assertTrue(suggestion.endswith("？"))

    def test_core_twists_are_not_revealed_in_surface(self) -> None:
        forbidden_terms = {
            "writer-hidden-camera": ("摄像头", "人体残肢", "连环杀手"),
            "twenty-five-point-five": ("拦腰截断", "下半身", "金属板"),
            "storage-room-exit": ("肇事司机", "囚禁", "原来的男友"),
            "photo-swap-photo": ("床下", "一只脚", "藏着人"),
        }
        for story_id, terms in forbidden_terms.items():
            with self.subTest(story=story_id):
                surface = self.stories[story_id]["surface"]
                for term in terms:
                    self.assertNotIn(term, surface)

    def test_custom_bank_keeps_horror_ratings(self) -> None:
        for story_id, story in self.stories.items():
            with self.subTest(story=story_id):
                self.assertIn(story["scale"], ("惊悚", "重口"))
                self.assertIn(
                    "惊悚恐怖",
                    [story["primary_genre"]]
                    + story.get("secondary_genres", []),
                )


if __name__ == "__main__":
    unittest.main()
