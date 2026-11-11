"""Build a structured story bank from OCR section data with the local model."""

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
VALID_GENRES = [
    "生活悬疑",
    "轻松脑洞",
    "社会派",
    "惊悚恐怖",
    "科幻实验室",
    "校园",
    "职场",
    "家庭伦理",
    "历史民国",
    "犯罪推理",
]
VALID_DIFFICULTIES = ["入门", "进阶", "烧脑"]
VALID_SCALES = ["无怖", "惊悚", "重口"]


SYSTEM_PROMPT = """你是中文海龟汤题库编辑。你只整理用户提供的OCR文本，不新增原文没有的核心设定。
输出一个严格JSON对象，不要Markdown，不要解释。

任务：
1. 修复明显OCR错字和断行，但保留故事原意、人物关系和反转。
2. surface只保留汤面异常现象，不泄露bottom中的答案、凶手、机关或真相。
3. bottom整理成逻辑完整、因果闭环的汤底；保留必要的暴力/恐怖信息。
4. 从bottom提取恰好5条原子事实，全部必须truth=true，而且都能在bottom中找到直接依据。
5. 不要设计false事实，不要把猜测、否定项或meta说明放进facts。
6. 每条事实给2到4个中文aliases；aliases要能帮助玩家自然提问。
7. 生成2条由浅入深的提示，不能直接复述bottom。
8. 生成3条示例问题，全部必须能用“是/不是”回答。禁止“为什么、谁、什么、哪里、怎么、如何、多少、多久、哪一”这类开放开头；但“她知道发生了什么吗？”这种可用是/不是回答的整句允许。
9. 题材只能从以下选择：生活悬疑、轻松脑洞、社会派、惊悚恐怖、科幻实验室、校园、职场、家庭伦理、历史民国、犯罪推理。
10. difficulty只能是：入门、进阶、烧脑；文件名已经给出难度时必须服从。
11. scale只能是：无怖、惊悚、重口。出现尸体、肢解、性暴力、虐待、猎奇死亡时用重口；普通灵异、跟踪、犯罪或紧张氛围用惊悚；没有恐惧内容用无怖。

固定输出结构：
{
  "title": "标题",
  "primary_genre": "惊悚恐怖",
  "secondary_genres": ["犯罪推理"],
  "difficulty": "进阶",
  "scale": "惊悚",
  "tags": ["标签1", "标签2"],
  "warnings": [],
  "surface": "整理后的汤面",
  "bottom": "整理后的完整汤底",
  "facts": [
    {
      "description": "事实描述",
      "truth": true,
      "aliases": ["别名1", "别名2"]
    }
  ],
  "hints": ["提示1", "提示2"],
  "suggestions": ["是/不是问题1？", "是/不是问题2？", "是/不是问题3？"]
}
"""


def clean_model_json(content: str) -> Optional[Dict[str, Any]]:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def source_number(source_key: str) -> int:
    match = re.match(r"^0*(\d+)", source_key)
    if not match:
        raise ValueError("cannot parse source number: {0}".format(source_key))
    return int(match.group(1))


def difficulty_hint(source_key: str) -> str:
    if "低难度" in source_key:
        return "入门"
    if "中难度" in source_key:
        return "进阶"
    if "高难度" in source_key:
        return "烧脑"
    return ""


def request_story(story: Dict[str, Any]) -> str:
    user_prompt = (
        "【文件名】\n{key}\n"
        "【难度线索】\n{difficulty}\n"
        "【原汤面OCR】\n{surface}\n"
        "【思路提示OCR，仅帮助你理解】\n{hints}\n"
        "【原汤底OCR】\n{bottom}\n"
        "【主持人手册OCR，仅帮助你理解】\n{manual}\n"
    ).format(
        key=story.get("source_key", ""),
        difficulty=difficulty_hint(story.get("source_key", "")),
        surface=story.get("surface", ""),
        hints=story.get("hints_text", ""),
        bottom=story.get("bottom", ""),
        manual=story.get("host_notes", ""),
    )
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
            "max_tokens": 1800,
            "stream": False,
            "response_format": {"type": "json_object"},
        },
        timeout=90,
    )
    response.raise_for_status()
    payload = response.json()
    return payload["choices"][0]["message"]["content"]


def normalize_story(
    payload: Dict[str, Any],
    section: Dict[str, Any],
) -> Dict[str, Any]:
    number = source_number(section["source_key"])
    story = {
        "id": "bali-{0:03d}".format(number),
        "title": section["title"],
        "primary_genre": str(payload.get("primary_genre", "")).strip(),
        "secondary_genres": [
            str(item).strip()
            for item in payload.get("secondary_genres", [])
            if str(item).strip() in VALID_GENRES
        ],
        "difficulty": (
            difficulty_hint(section["source_key"])
            or str(payload.get("difficulty", "")).strip()
        ),
        "scale": str(payload.get("scale", "")).strip(),
        "tags": [
            str(item).strip()
            for item in payload.get("tags", [])
            if str(item).strip()
        ],
        "warnings": [
            str(item).strip()
            for item in payload.get("warnings", [])
            if str(item).strip()
        ],
        "surface": str(payload.get("surface", "")).strip(),
        "bottom": str(payload.get("bottom", "")).strip(),
        "facts": [],
        "hints": [
            str(item).strip()
            for item in payload.get("hints", [])
            if str(item).strip()
        ],
        "suggestions": [
            str(item).strip()
            for item in payload.get("suggestions", [])
            if str(item).strip()
        ],
        "source_key": section["source_key"],
        "source_number": number,
        "source_title": section["title"],
        "source_author": "八里十",
    }
    for fact_index, fact in enumerate(payload.get("facts", []), start=1):
        if not isinstance(fact, dict):
            continue
        description = str(fact.get("description", "")).strip()
        aliases = [
            str(item).strip()
            for item in fact.get("aliases", [])
            if str(item).strip()
        ]
        if not description or not aliases:
            continue
        story["facts"].append(
            {
                "id": "fact-{0}".format(fact_index),
                "description": description,
                "truth": bool(fact.get("truth")),
                "aliases": aliases,
            }
        )
    return story


def is_binary_suggestion(text: str) -> bool:
    normalized = re.sub(r"\s+", "", text)
    if re.match(r"^是/?不是", normalized):
        return True
    if re.match(r"^(为什么|为何|怎么|如何|谁|什么|哪里|哪儿|多少|多久|哪一)", normalized):
        return False
    if re.search(r"(为什么|为何|怎么|如何|谁|哪里|哪儿|多少|多久|哪一)", normalized):
        return False
    if re.search(
        r"(是否|是不是|有没有|会不会|能不能|可不可以|对不对|算不算)",
        normalized,
    ) or re.search(r"[吗？?]$", normalized):
        return True
    return "什么" not in normalized


def validate_story(story: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if story["primary_genre"] not in VALID_GENRES:
        errors.append("invalid primary_genre")
    if any(item not in VALID_GENRES for item in story["secondary_genres"]):
        errors.append("invalid secondary_genres")
    if story["difficulty"] not in VALID_DIFFICULTIES:
        errors.append("invalid difficulty")
    if story["scale"] not in VALID_SCALES:
        errors.append("invalid scale")
    if len(story["surface"]) < 15:
        errors.append("surface too short")
    if len(story["bottom"]) < 30:
        errors.append("bottom too short")
    if len(story["facts"]) != 5:
        errors.append("facts must be exactly 5")
    if len({fact.get("id") for fact in story["facts"]}) != len(story["facts"]):
        errors.append("fact ids must be unique")
    if any(not fact["truth"] for fact in story["facts"]):
        errors.append("all facts must be true")
    if len(story["hints"]) < 2:
        errors.append("at least 2 hints are required")
    if len(story["suggestions"]) != 3:
        errors.append("exactly 3 suggestions are required")
    for suggestion in story["suggestions"]:
        if not is_binary_suggestion(suggestion):
            errors.append("suggestion is not binary: {0}".format(suggestion))
            break
    if "�" in story["surface"] + story["bottom"]:
        errors.append("replacement character remains")
    return errors


def build_story(section: Dict[str, Any]) -> Dict[str, Any]:
    last_content = ""
    last_errors: List[str] = []
    for attempt in range(3):
        content = request_story(section)
        last_content = content
        payload = clean_model_json(content)
        if payload is None:
            last_errors = ["invalid JSON"]
            continue
        story = normalize_story(payload, section)
        errors = validate_story(story)
        if not errors:
            return story
        last_errors = errors
        section = dict(section)
        section["host_notes"] += (
            "\n上一次输出存在错误：{0}。请修正并只输出JSON。"
            .format("; ".join(errors))
        )
    raise ValueError(
        "failed after retries: {0}; raw={1}".format(
            "; ".join(last_errors),
            last_content[:500],
        )
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
    sections = json.loads(input_path.read_text(encoding="utf-8"))["stories"]
    if args.offset:
        sections = sections[args.offset:]
    if args.limit:
        sections = sections[: args.limit]

    manager: Optional[LlamaServerManager] = None
    try:
        health = requests.get(
            "http://127.0.0.1:11435/health",
            timeout=3,
        )
        health.raise_for_status()
    except Exception:
        manager = LlamaServerManager()
        if not manager.start():
            print("local model could not be started", file=sys.stderr)
            return 1

    existing: Dict[str, Any] = {}
    if output_path.exists():
        existing_payload = json.loads(output_path.read_text(encoding="utf-8"))
        for story in existing_payload.get("stories", []):
            for fact_index, fact in enumerate(
                story.get("facts", []),
                start=1,
            ):
                fact.setdefault("id", "fact-{0}".format(fact_index))
            existing[story["source_key"]] = story

    try:
        for index, section in enumerate(sections, start=1):
            source_key = section["source_key"]
            if source_key in existing:
                existing[source_key]["title"] = section["title"]
                print(
                    "[{0}/{1}] skip {2}".format(
                        index,
                        len(sections),
                        source_key,
                    )
                )
                continue
            print("[{0}/{1}] build {2}".format(index, len(sections), source_key))
            started = time.monotonic()
            story = build_story(section)
            existing[source_key] = story
            elapsed = time.monotonic() - started
            print("  done in {0:.1f}s: {1}".format(elapsed, story["title"]))

            payload = {
                "schema_version": 1,
                "dataset": {
                    "id": "bali-ten-original-horror-v1",
                    "name": "八里十原创海龟汤整理题库 V1",
                    "version": "1.0.0",
                    "source": "用户提供的八里十原创海龟汤图片",
                    "source_author": "八里十",
                    "rights_status": "需取得原作者授权后才能公开发布",
                    "notes": "OCR提取并经本地模型整理，发布前需要人工复核",
                },
                "genres": VALID_GENRES,
                "difficulties": VALID_DIFFICULTIES,
                "scales": VALID_SCALES,
                "stories": sorted(
                    existing.values(),
                    key=lambda item: item["source_number"],
                ),
            }
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    finally:
        if manager is not None:
            manager.shutdown()

    if not sections:
        return 0
    payload = {
        "schema_version": 1,
        "dataset": {
            "id": "bali-ten-original-horror-v1",
            "name": "八里十原创海龟汤整理题库 V1",
            "version": "1.0.0",
            "source": "用户提供的八里十原创海龟汤图片",
            "source_author": "八里十",
            "rights_status": "需取得原作者授权后才能公开发布",
            "notes": "OCR提取并经本地模型整理，发布前需要人工复核",
        },
        "genres": VALID_GENRES,
        "difficulties": VALID_DIFFICULTIES,
        "scales": VALID_SCALES,
        "stories": sorted(
            existing.values(),
            key=lambda item: item["source_number"],
        ),
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        "completed {0} stories; output={1}".format(
            len(existing),
            output_path,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
