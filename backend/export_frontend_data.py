"""Generate the browser fallback snapshot consumed by stories.js."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
SEED_FILE = ROOT / "backend" / "stories.json"
OUTPUT_FILE = ROOT / "stories.js"


def _public_story(story: Dict[str, Any]) -> Dict[str, Any]:
    genres = story.get("genres") or []
    if not genres:
        genres = [story["primary_genre"]] + story.get(
            "secondary_genres", []
        )
        genres = list(dict.fromkeys(genres))
    return {
        "id": story["id"],
        "title": story["title"],
        "primary_genre": story["primary_genre"],
        "secondary_genres": story.get("secondary_genres", []),
        "genres": genres,
        "tags": story.get("tags", []),
        "difficulty": story["difficulty"],
        "scale": story["scale"],
        "warnings": story.get("warnings", []),
        "surface": story["surface"],
        "bottom": story["bottom"],
        "facts": story["facts"],
        "hints": story["hints"],
        "suggestions": story["suggestions"],
    }


def main() -> int:
    with SEED_FILE.open("r", encoding="utf-8") as handle:
        seed = json.load(handle)

    stories: List[Dict[str, Any]] = [
        _public_story(story) for story in seed["stories"]
    ]
    payload = {
        "schema_version": seed.get("schema_version", 1),
        "genres": seed["genres"],
        "difficulties": seed["difficulties"],
        "scales": seed["scales"],
        "stories": stories,
    }
    content = (
        "(function () {\n"
        '  "use strict";\n'
        "  window.SOUP_DATA = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
        "  window.STORIES = window.SOUP_DATA.stories;\n"
        "})();\n"
    )
    OUTPUT_FILE.write_text(content, encoding="utf-8")
    print("wrote {0} stories to {1}".format(len(stories), OUTPUT_FILE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
