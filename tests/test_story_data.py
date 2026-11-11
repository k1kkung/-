"""Content metadata checks for the story repository."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORIES_FILE = ROOT / "backend" / "stories.json"


class StoryMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with STORIES_FILE.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        cls.stories = {
            story["id"]: story for story in payload["stories"]
        }

    def test_bricked_basement_is_grounded_life_mystery(self) -> None:
        story = self.stories["bricked-basement-door"]

        self.assertEqual(story["primary_genre"], "生活悬疑")
        self.assertIn("历史民国", story["secondary_genres"])
        self.assertEqual(story["scale"], "无怖")
        self.assertNotEqual(story["primary_genre"], "惊悚恐怖")

    def test_radio_story_suggestions_are_binary_questions(self) -> None:
        story = self.stories["radio-announces-deaths"]
        open_markers = ("为什么", "谁", "什么", "哪里", "怎么", "如何")

        self.assertEqual(story["primary_genre"], "生活悬疑")
        self.assertIn("社会派", story["secondary_genres"])
        self.assertEqual(story["scale"], "无怖")
        for suggestion in story["suggestions"]:
            with self.subTest(suggestion=suggestion):
                self.assertTrue(suggestion.endswith("？"))
                self.assertFalse(
                    any(marker in suggestion for marker in open_markers)
                )

    def test_every_story_has_a_visible_binary_example(self) -> None:
        open_markers = ("为什么", "为何", "怎么", "如何", "谁", "什么", "哪里", "哪儿", "多少", "多久", "哪一")

        for story in self.stories.values():
            with self.subTest(story=story["id"]):
                self.assertTrue(
                    any(
                        not any(
                            marker in suggestion
                            for marker in open_markers
                        )
                        for suggestion in story["suggestions"]
                    )
                )

    def test_humid_room_does_not_reveal_pipe_in_surface(self) -> None:
        story = self.stories["house-humidifies"]

        self.assertNotIn("排水管", story["surface"])
        self.assertEqual(story["primary_genre"], "生活悬疑")
        self.assertEqual(story["scale"], "无怖")
        self.assertIn("排水管", story["bottom"])


if __name__ == "__main__":
    unittest.main()
