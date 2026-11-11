"""Verify and repair story facts against their canonical story bottoms."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import LlamaServerManager  # noqa: E402


MODEL_ENDPOINT = "http://127.0.0.1:11435/v1/chat/completions"
SYSTEM_PROMPT = """你是海龟汤事实核验器。只根据提供的bottom核验facts，不得新增设定。
输出严格JSON对象，不要Markdown，不要解释。

规则：
1. 每条fact必须有evidence，evidence必须逐字复制bottom中的原文片段。
2. 如果bottom直接支持description，truth=true。
3. 如果bottom明确否定description，truth=false，并改写description为被否定命题。
4. 如果bottom只是说某角色“听说、认为、相信、误以为、传说”某个功效，不能把该功效写成客观事实；应改写为“某人听说/相信某功效”的真实事实，truth=true。
5. 无法核验的描述要改写成bottom能直接支持的句子。
6. 一共恰好5条facts，每条2到4个aliases。

固定输出：
{
  "facts": [
    {
      "description": "核验后的事实",
      "truth": true,
      "aliases": ["别名1", "别名2"],
      "evidence": "bottom中的逐字原文"
    }
  ]
}
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


def request_verification(story: Dict[str, Any]) -> str:
    response = requests.post(
        MODEL_ENDPOINT,
        json={
            "model": "local",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "【bottom】\n{0}\n\n【facts】\n{1}"
                    ).format(
                        story["bottom"],
                        json.dumps(
                            story["facts"],
                            ensure_ascii=False,
                            indent=2,
                        ),
                    ),
                },
            ],
            "temperature": 0.0,
            "top_p": 0.1,
            "max_tokens": 1800,
            "stream": False,
            "response_format": {"type": "json_object"},
        },
        timeout=90,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def normalize_facts(
    payload: Dict[str, Any],
    bottom: str,
) -> List[Dict[str, Any]]:
    facts = []
    normalized_bottom = re.sub(r"\s+", "", bottom)
    bottom_segments = [
        re.sub(r"\s+", "", segment)
        for segment in re.split(r"[。！？!?；;.]+", bottom)
        if segment.strip()
    ]
    for index, fact in enumerate(payload.get("facts", []), start=1):
        if not isinstance(fact, dict):
            continue
        description = str(fact.get("description", "")).strip()
        evidence = str(fact.get("evidence", "")).strip()
        aliases = [
            str(item).strip()
            for item in fact.get("aliases", [])
            if str(item).strip()
        ]
        if not description or not evidence or not aliases:
            continue
        normalized_evidence = re.sub(r"\s+", "", evidence)
        evidence_supported = normalized_evidence in normalized_bottom
        if not evidence_supported and bottom_segments:
            evidence_supported = any(
                SequenceMatcher(
                    None,
                    normalized_evidence,
                    segment,
                ).ratio()
                >= 0.86
                for segment in bottom_segments
            )
        if not evidence_supported:
            continue
        facts.append(
            {
                "id": "fact-{0}".format(index),
                "description": description,
                "truth": bool(fact.get("truth")),
                "aliases": aliases,
                "evidence": evidence,
            }
        )
    return facts


def fallback_facts(
    facts: List[Dict[str, Any]],
    bottom: str,
) -> List[Dict[str, Any]]:
    if len(facts) >= 5:
        result = facts[:5]
        for index, fact in enumerate(result, start=1):
            fact["id"] = "fact-{0}".format(index)
        return result
    used_evidence = {
        re.sub(r"\s+", "", fact.get("evidence", ""))
        for fact in facts
    }
    segments = [
        segment.strip()
        for segment in re.split(r"[。！？!?；;\n]+", bottom)
        if len(segment.strip()) >= 10
    ]
    for segment in segments:
        normalized_segment = re.sub(r"\s+", "", segment)
        if normalized_segment in used_evidence:
            continue
        aliases = [
            part.strip(" ，,、")
            for part in re.split(r"[，,、]", segment)
            if len(part.strip(" ，,、")) >= 2
        ]
        if not aliases:
            aliases = [segment[:16]]
        facts.append(
            {
                "id": "fact-{0}".format(len(facts) + 1),
                "description": segment,
                "truth": True,
                "aliases": aliases[:4],
                "evidence": segment,
            }
        )
        used_evidence.add(normalized_segment)
        if len(facts) == 5:
            break
    result = facts[:5]
    for index, fact in enumerate(result, start=1):
        fact["id"] = "fact-{0}".format(index)
    return result


def verify_story(story: Dict[str, Any]) -> Dict[str, Any]:
    last_content = ""
    for _ in range(3):
        content = request_verification(story)
        last_content = content
        payload = clean_json(content)
        if payload is None:
            continue
        facts = fallback_facts(
            normalize_facts(payload, story["bottom"]),
            story["bottom"],
        )
        if len(facts) == 5:
            repaired = dict(story)
            repaired["facts"] = facts
            return repaired
    raise ValueError(
        "fact verification failed for {0}: {1}".format(
            story["id"],
            last_content[:500],
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
            if (
                candidate
                and len(candidate.get("facts", [])) == 5
                and all("evidence" in fact for fact in candidate["facts"])
            ):
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
            if (
                len(story.get("facts", [])) == 5
                and all("evidence" in fact for fact in story["facts"])
            ):
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
                "[{0}/{1}] verify {2} {3}".format(
                    index,
                    len(stories),
                    story["id"],
                    story["title"],
                )
            )
            started = time.monotonic()
            try:
                repaired = verify_story(story)
                repaired["review_status"] = "needs_human_review"
            except Exception as exc:
                print("  failed: {0}".format(exc))
                story["review_status"] = "fact_verification_failed"
                repaired = story
            payload["stories"][args.offset + index - 1] = repaired
            write_payload(output_path, payload)
            print(
                "  done in {0:.1f}s".format(
                    time.monotonic() - started
                )
            )
    finally:
        if manager is not None:
            manager.shutdown()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
