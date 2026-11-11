"""Evaluate the local judge against a fixed set of labeled questions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    from app import LocalJudgeService
except ImportError:
    from backend.app import LocalJudgeService


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = Path(__file__).resolve().parent / "judge_cases.json"
VALID_ANSWERS = {"yes", "no", "irrelevant", "unknown"}


def load_cases(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list) or not cases:
        raise ValueError("case file must contain a non-empty cases list")

    normalized: List[Dict[str, str]] = []
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError("case {0} must be an object".format(index))
        normalized_case = {
            "id": str(case.get("id") or "case-{0}".format(index)),
            "story_id": str(case.get("story_id", "")).strip(),
            "question": str(case.get("question", "")).strip(),
            "expected": str(case.get("expected", "")).strip().lower(),
        }
        history = case.get("history")
        if isinstance(history, list):
            normalized_case["history"] = history
        if (
            not normalized_case["story_id"]
            or not normalized_case["question"]
            or normalized_case["expected"] not in VALID_ANSWERS
        ):
            raise ValueError("case {0} is incomplete".format(index))
        normalized.append(normalized_case)
    return normalized


def run(cases: List[Dict[str, str]]) -> Dict[str, Any]:
    service = LocalJudgeService()
    if not service.start():
        raise RuntimeError("local judge service did not become ready")

    results = []
    try:
        for case in cases:
            actual = service.judge(
                case["story_id"],
                case["question"],
                case.get("history"),
            )
            results.append(
                {
                    **case,
                    "actual": actual or "fallback",
                    "correct": actual == case["expected"],
                }
            )
    finally:
        service.shutdown()

    total = len(results)
    correct = sum(1 for item in results if item["correct"])
    fallback = sum(
        1 for item in results if item["actual"] == "fallback"
    )
    critical_inversion = sum(
        1
        for item in results
        if {item["expected"], item["actual"]} == {"yes", "no"}
    )
    return {
        "total": total,
        "correct": correct,
        "accuracy": correct / total,
        "fallback": fallback,
        "critical_inversion": critical_inversion,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the SOUP.AI judge against labeled cases."
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES,
        help="UTF-8 JSON case file",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the full report as JSON",
    )
    args = parser.parse_args()

    try:
        report = run(load_cases(args.cases))
    except Exception as exc:
        print("evaluation failed: {0}".format(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for item in report["results"]:
            marker = "PASS" if item["correct"] else "FAIL"
            print(
                "{0} {1}: expected={2} actual={3}".format(
                    marker,
                    item["id"],
                    item["expected"],
                    item["actual"],
                )
            )
        print(
            "accuracy={0:.1%} correct={1}/{2} fallback={3} "
            "critical_inversion={4}".format(
                report["accuracy"],
                report["correct"],
                report["total"],
                report["fallback"],
                report["critical_inversion"],
            )
        )
    return 0 if report["critical_inversion"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
