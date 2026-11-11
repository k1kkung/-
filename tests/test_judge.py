"""Unit tests for the bottom-based AI judge contract."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import LocalJudgeService  # noqa: E402


STORY = {
    "id": "test-story",
    "title": "Test story",
    "surface": "A clean sock appears in a shared fridge.",
    "bottom": (
        "A roommate is an emergency volunteer. "
        "The sock was used to bandage an injured person. "
        "He planned to clean it after work."
    ),
    "facts": {
        "volunteer": {
            "id": "volunteer",
            "description": "The roommate is an emergency volunteer.",
            "truth": True,
            "aliases": ["emergency volunteer"],
        },
        "food": {
            "id": "food",
            "description": "The sock is related to food.",
            "truth": False,
            "aliases": ["food"],
        },
    },
    "suggestions": [
        "Is the sock related to an emergency?",
        "Was the sock used as a bandage?",
        "Is the roommate hiding something?",
    ],
}


def make_content(
    answer: str,
    evidence: str = "",
    confidence: float = 0.9,
) -> str:
    return json.dumps(
        {
            "answer": answer,
            "evidence": evidence,
            "self_confidence": confidence,
        }
    )


class FakeLlama:
    def status(self) -> str:
        return "ready"


class FakeDatabase:
    def __init__(self, story: dict[str, Any]) -> None:
        self.story = story

    def get_judge_story(self, story_id: str) -> dict[str, Any] | None:
        if story_id == self.story["id"]:
            return self.story
        return None

    def get_static_hint(
        self,
        story_id: str,
        hints_used: int,
    ) -> dict[str, Any] | None:
        if story_id != self.story["id"]:
            return None
        return {
            "hint": "Static hint {0}".format(hints_used + 1),
            "hint_index": hints_used,
            "used": hints_used + 1,
            "max": 2,
            "source": "static",
        }


class JudgeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = LocalJudgeService.__new__(LocalJudgeService)
        self.service.min_confidence = 0.65

    def test_prompt_uses_bottom_as_primary_evidence(self) -> None:
        prompt = self.service._build_system_prompt(STORY)

        self.assertIn("【完整汤底】", prompt)
        self.assertIn(STORY["bottom"], prompt)
        self.assertIn("不得限制你只能从事实表中选答案", prompt)
        self.assertIn("unknown", prompt)
        self.assertIn("只有引入故事外的新话题时", prompt)
        self.assertIn("一件雨衣是什么品牌", prompt)
        self.assertNotIn("fact_id 必须是", prompt)

    def test_accepts_supported_answer_with_exact_evidence(self) -> None:
        parsed = self.service._parse_model_result(
            make_content(
                "yes",
                "The sock was used to bandage an injured person.",
            ),
            STORY,
        )

        self.assertIsNotNone(parsed)
        answer, evidence, confidence = parsed
        self.assertEqual(answer, "yes")
        self.assertIn(evidence, STORY["bottom"])
        self.assertAlmostEqual(confidence, 0.9)

    def test_accepts_reference_fact_as_exact_evidence(self) -> None:
        parsed = self.service._parse_model_result(
            make_content(
                "yes",
                STORY["facts"]["volunteer"]["description"],
            ),
            STORY,
        )

        self.assertIsNotNone(parsed)
        answer, evidence, confidence = parsed
        self.assertEqual(answer, "yes")
        self.assertEqual(
            evidence,
            STORY["facts"]["volunteer"]["description"],
        )
        self.assertAlmostEqual(confidence, 0.9)

    def test_accepts_evidence_combined_from_two_sources(self) -> None:
        evidence = (
            "A roommate is an emergency volunteer. "
            "The sock is related to food."
        )
        parsed = self.service._parse_model_result(
            make_content("no", evidence),
            STORY,
        )

        self.assertIsNotNone(parsed)
        answer, returned_evidence, confidence = parsed
        self.assertEqual(answer, "no")
        self.assertEqual(returned_evidence, evidence)
        self.assertAlmostEqual(confidence, 0.9)

    def test_accepts_two_sentences_from_known_sources(self) -> None:
        evidence = (
            "A roommate is an emergency volunteer. "
            "The sock was used to bandage an injured person."
        )
        parsed = self.service._parse_model_result(
            make_content("yes", evidence),
            STORY,
        )

        self.assertIsNotNone(parsed)
        answer, returned_evidence, confidence = parsed
        self.assertEqual(answer, "yes")
        self.assertEqual(returned_evidence, evidence)
        self.assertAlmostEqual(confidence, 0.9)

    def test_accepts_paraphrased_evidence_with_high_similarity(self) -> None:
        with (ROOT / "backend" / "stories.json").open(
            "r",
            encoding="utf-8",
        ) as handle:
            payload = json.load(handle)
        raw_story = next(
            story
            for story in payload["stories"]
            if story["id"] == "radio-announces-deaths"
        )
        story = {
            **raw_story,
            "facts": {
                fact["id"]: fact for fact in raw_story["facts"]
            },
        }
        evidence = (
            "广播其实是医院临终关怀病房的内部频道。"
            "广播每天播报的是需要家属探望的病人姓名，不是死亡名单。"
        )

        parsed = self.service._parse_model_result(
            make_content("no", evidence),
            story,
        )

        self.assertIsNotNone(parsed)
        answer, returned_evidence, confidence = parsed
        self.assertEqual(answer, "no")
        self.assertEqual(returned_evidence, evidence)
        self.assertAlmostEqual(confidence, 0.9)

    def test_returns_unknown_for_paraphrased_evidence(self) -> None:
        parsed = self.service._parse_model_result(
            make_content(
                "yes",
                "The sock was used as a bandage.",
            ),
            STORY,
        )

        self.assertIsNotNone(parsed)
        answer, evidence, confidence = parsed
        self.assertEqual(answer, "unknown")
        self.assertEqual(evidence, "The sock was used as a bandage.")
        self.assertAlmostEqual(confidence, 0.9)

    def test_rejects_answer_that_conflicts_with_reference_fact(self) -> None:
        parsed = self.service._parse_model_result(
            make_content(
                "yes",
                STORY["facts"]["food"]["description"],
            ),
            STORY,
        )

        self.assertIsNotNone(parsed)
        answer, evidence, confidence = parsed
        self.assertEqual(answer, "unknown")
        self.assertEqual(evidence, STORY["facts"]["food"]["description"])
        self.assertAlmostEqual(confidence, 0.9)

    def test_accepts_unknown_and_irrelevant_without_evidence(self) -> None:
        for expected in ("unknown", "irrelevant"):
            with self.subTest(expected=expected):
                parsed = self.service._parse_model_result(
                    make_content(expected),
                    STORY,
                )
                self.assertEqual(parsed, (expected, "", 0.9))

    def test_rejects_malformed_answer_or_confidence(self) -> None:
        invalid_contents = [
            "not json",
            make_content("maybe"),
            make_content("yes", "", 1.2),
            json.dumps(
                {
                    "answer": "yes",
                    "evidence": STORY["bottom"],
                }
            ),
        ]

        for content in invalid_contents:
            with self.subTest(content=content):
                self.assertIsNone(
                    self.service._parse_model_result(content, STORY)
                )

    def test_low_confidence_becomes_unknown(self) -> None:
        service = LocalJudgeService.__new__(LocalJudgeService)
        service.llama = FakeLlama()
        service.db = FakeDatabase(STORY)
        service.min_confidence = 0.65
        service.request_timeout = 30.0
        service._judge_with_model = lambda story, question, history: (
            "yes",
            "The sock was used to bandage an injured person.",
            0.4,
        )

        self.assertEqual(service.judge(STORY["id"], "test question"), "unknown")

    def test_static_hint_includes_suggested_question(self) -> None:
        service = LocalJudgeService.__new__(LocalJudgeService)
        service.llama = FakeLlama()
        service.db = FakeDatabase(STORY)

        first = service.get_hint(STORY["id"], 0, False)
        second = service.get_hint(STORY["id"], 1, False)

        self.assertEqual(
            first["suggested_question"],
            STORY["suggestions"][0],
        )
        self.assertEqual(
            second["suggested_question"],
            STORY["suggestions"][1],
        )

    def test_ai_hint_prompt_excludes_false_facts(self) -> None:
        service = LocalJudgeService.__new__(LocalJudgeService)
        captured = {}

        def fake_completion(prompt, question):
            captured["prompt"] = prompt
            return '{"hint":"A short hint"}'

        service._request_completion = fake_completion
        hint = service._request_ai_hint(STORY, 0)

        self.assertEqual(hint, "A short hint")
        self.assertIn(
            STORY["facts"]["volunteer"]["description"],
            captured["prompt"],
        )
        self.assertNotIn(
            STORY["facts"]["food"]["description"],
            captured["prompt"],
        )

    def test_user_prompt_contains_recent_history(self) -> None:
        prompt = LocalJudgeService._build_user_prompt(
            "Was he the volunteer?",
            [
                {
                    "question": "Was the sock used as a bandage?",
                    "answer": "yes",
                }
            ],
        )

        self.assertIn("Was the sock used as a bandage?", prompt)
        self.assertIn("裁判：是", prompt)
        self.assertIn("Was he the volunteer?", prompt)


if __name__ == "__main__":
    unittest.main()
