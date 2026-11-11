"""Generate short reveal summaries for the story bank."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import LlamaServerManager  # noqa: E402


MODEL_ENDPOINT = "http://127.0.0.1:11435/v1/chat/completions"
SYSTEM_PROMPT = """你是中文海龟汤编辑。请把完整汤底压缩成适合网页揭晓的短摘要。
只输出严格JSON对象，不要Markdown，不要解释。

要求：
1. 只使用bottom中已有的信息，不新增设定。
2. 保留核心异常、真实原因、关键人物行为、反转和结果。
3. 不复述汤面，不写“这个故事讲述”等套话。
4. 100到180个中文字符；如果bottom本身不足100字，则直接使用bottom原文。
5. 保留必要的人物、亲属关系和关键物件，避免只写抽象概括。

固定输出：{"summary":"短摘要"}
"""


def clean_json(content: str) -> Optional[Dict[str, Any]]:
    content = re.sub(r"^```(?:json)?\s*", "", content.strip())
    content = re.sub(r"\s*```$", "", content)
    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def request_summary(story: Dict[str, Any], feedback: str = "") -> str:
    user_prompt = "【标题】\n{0}\n【完整汤底】\n{1}".format(
        story["title"],
        story["bottom"],
    )
    if feedback:
        user_prompt += "\n【修正要求】\n" + feedback
    response = requests.post(
        MODEL_ENDPOINT,
        json={
            "model": "local",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "top_p": 0.2,
            "max_tokens": 500,
            "stream": False,
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def summary_bounds(bottom: str) -> tuple[int, int]:
    if len(bottom) <= 100:
        return len(bottom), len(bottom)
    return 40, min(180, len(bottom))


def generate_summary(story: Dict[str, Any]) -> str:
    if len(story["bottom"]) <= 100:
        return story["bottom"]
    minimum, maximum = summary_bounds(story["bottom"])
    feedback = ""
    last_content = ""
    last_length = 0
    for _ in range(3):
        content = request_summary(story, feedback)
        last_content = content
        payload = clean_json(content)
        if payload is None:
            feedback = "输出不是合法JSON，请只输出固定JSON结构。"
            continue
        summary = str(payload.get("summary", "")).strip()
        last_length = len(summary)
        if minimum <= len(summary) <= maximum:
            return summary
        feedback = "上一次摘要长度为{0}，必须控制在{1}到{2}字，并保留核心反转。".format(
            len(summary),
            minimum,
            maximum,
        )
    raise ValueError(
        "summary generation failed for {0}: length={1} raw={2}".format(
            story["id"],
            last_length,
            last_content[:300],
        )
    )


def write_payload(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if output_path.exists():
        existing_payload = json.loads(
            output_path.read_text(encoding="utf-8")
        )
        existing = {
            story["id"]: story
            for story in existing_payload.get("stories", [])
        }
        for index, story in enumerate(payload["stories"]):
            candidate = existing.get(story["id"])
            if candidate and candidate.get("summary"):
                payload["stories"][index] = candidate

    try:
        requests.get(
            "http://127.0.0.1:11435/health",
            timeout=3,
        ).raise_for_status()
        manager = None
    except Exception:
        manager = LlamaServerManager()
        if not manager.start():
            print("local model could not be started", file=sys.stderr)
            return 1

    stories = payload["stories"][args.offset :]
    if args.limit:
        stories = stories[: args.limit]

    try:
        for index, story in enumerate(stories, start=1):
            if story.get("summary"):
                print(
                    "[{0}/{1}] skip {2} {3}".format(
                        index,
                        len(stories),
                        story["id"],
                        story["title"],
                    )
                )
                continue
            print(
                "[{0}/{1}] summarize {2} {3}".format(
                    index,
                    len(stories),
                    story["id"],
                    story["title"],
                )
            )
            started = time.monotonic()
            summary = generate_summary(story)
            story["summary"] = summary
            payload["stories"][args.offset + index - 1] = story
            write_payload(output_path, payload)
            print(
                "  done in {0:.1f}s length={1}".format(
                    time.monotonic() - started,
                    len(summary),
                )
            )
    finally:
        if manager is not None:
            manager.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
