"""Split OCR story panels into surface, hints, bottom, and host notes."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]


def clean_lines(text: str, title: str) -> List[str]:
    cleaned: List[str] = []
    ignored = {
        title,
        "《{0}》".format(title),
        "八里十原创",
        "-八里十",
        "八里十",
    }
    ignored_markers = (
        "下页有思路提示",
        "下页有汤底",
        "汤底右滑",
        "汤底右划",
    )
    for raw_line in text.splitlines():
        line = raw_line.strip()
        line = re.sub(r"^[·•]\s*", "", line)
        line = re.sub(r"\s+", "", line)
        if not line or line in ignored:
            continue
        if line.isdigit():
            continue
        if any(marker in line for marker in ignored_markers):
            line = re.sub(
                "|".join(map(re.escape, ignored_markers)),
                "",
                line,
            ).strip()
            if not line:
                continue
        cleaned.append(line)
    return cleaned


def find_manual_panel(images: List[Dict[str, Any]]) -> int | None:
    for index, image in enumerate(images):
        text = str(image.get("text", ""))
        if "主持人手册" in text or "主持人手冊" in text:
            return index
    return None


def split_story(story: Dict[str, Any]) -> Dict[str, Any]:
    images = sorted(
        story.get("images", []),
        key=lambda item: int(item.get("panel", 0)),
    )
    title = str(story.get("title_guess", "")).strip()
    if not images:
        return {
            "source_key": story.get("key", ""),
            "title": title,
            "surface": "",
            "hints": [],
            "bottom": "",
            "host_notes": "",
            "warnings": ["no_images"],
        }

    surface_lines = clean_lines(str(images[0].get("text", "")), title)
    manual_index = find_manual_panel(images)

    hint_lines: List[str] = []
    if len(images) >= 3:
        hint_lines = clean_lines(str(images[1].get("text", "")), title)

    if len(images) == 2:
        bottom_start = 1
    elif len(images) >= 3:
        bottom_start = 2
    else:
        bottom_start = 1

    bottom_lines: List[str] = []
    for index, image in enumerate(images):
        if index < bottom_start or index == manual_index:
            continue
        bottom_lines.extend(clean_lines(str(image.get("text", "")), title))

    host_lines: List[str] = []
    if manual_index is not None:
        host_lines = clean_lines(
            str(images[manual_index].get("text", "")),
            title,
        )

    surface = "\n".join(surface_lines)
    bottom = "\n".join(bottom_lines)
    hints_text = "\n".join(hint_lines)
    warnings: List[str] = []
    if len(surface) < 20:
        warnings.append("surface_too_short")
    if len(bottom) < 20:
        warnings.append("bottom_too_short")
    if not hint_lines:
        warnings.append("no_hint_panel")
    if manual_index is None:
        warnings.append("no_host_manual")
    if "�" in surface + bottom + hints_text:
        warnings.append("replacement_character")

    return {
        "source_key": story.get("key", ""),
        "title": title,
        "surface": surface,
        "hints_text": hints_text,
        "bottom": bottom,
        "host_notes": "\n".join(host_lines),
        "warnings": warnings,
        "image_files": [image.get("file") for image in images],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    input_path = args.input if args.input.is_absolute() else ROOT / args.input
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    stories = [split_story(story) for story in payload["stories"]]

    result = {
        "source": str(input_path),
        "story_count": len(stories),
        "stories": stories,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("wrote {0} sections to {1}".format(len(stories), output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
