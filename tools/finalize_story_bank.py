"""Apply conservative content-rating rules and write the final story bank."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
HEAVY_PATTERN = re.compile(
    "尸|骨|割开|剖开|剖腹|挖出|残肢|强奸|强暴|性侵|侵犯|虐待|"
    "拐卖|吃人|人肉|自杀|活埋|分尸|斩|砍|刺死|毒死|烧死|"
    "器官|冥婚|虐杀"
)
SEXUAL_VIOLENCE_PATTERN = re.compile("强奸|强暴|性侵|侵犯")
CHILD_HARM_PATTERN = re.compile("孩子|儿童|男孩|女孩|弟弟|妹妹|学生")


def normalize_warnings(story: Dict[str, Any]) -> List[str]:
    warnings = [
        str(item).strip()
        for item in story.get("warnings", [])
        if str(item).strip()
    ]
    bottom = str(story.get("bottom", ""))
    if story.get("scale") == "重口":
        warnings.append("包含死亡、暴力或可能引起不适的描写")
    if SEXUAL_VIOLENCE_PATTERN.search(bottom):
        warnings.append("包含性暴力或侵害描写")
    if story.get("scale") == "重口" and CHILD_HARM_PATTERN.search(bottom):
        warnings.append("包含儿童受害或家庭创伤描写")
    return list(dict.fromkeys(warnings))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    payload = json.loads(input_path.read_text(encoding="utf-8"))

    for story in payload["stories"]:
        bottom = str(story.get("bottom", ""))
        for index, fact in enumerate(story.get("facts", []), start=1):
            fact["id"] = "fact-{0}".format(index)
        if HEAVY_PATTERN.search(bottom):
            story["scale"] = "重口"
        elif story.get("scale") == "重口":
            story["scale"] = "惊悚"
        story["warnings"] = normalize_warnings(story)
        story["review_status"] = "needs_human_review"

    payload["dataset"]["name"] = "八里十原创海龟汤整理题库 V1"
    payload["dataset"]["review_status"] = "needs_human_review"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("wrote {0} stories to {1}".format(len(payload["stories"]), output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
