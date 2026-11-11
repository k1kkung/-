"""Validate a story-bank JSON file against the application schema."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

try:
    from story_repository import StoryDatabase
except ImportError:
    from backend.story_repository import StoryDatabase


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a story bank.")
    parser.add_argument("input", type=Path)
    args = parser.parse_args()

    input_path = args.input
    if not input_path.is_absolute():
        input_path = ROOT / input_path

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = StoryDatabase(
                input_path.resolve(),
                Path(temp_dir) / "validation.db",
            )
            database.initialize()
            report = database.validate_current_seed()
            report["sample_ids"] = [
                story["id"]
                for story in database.search_stories(page_size=5)["items"]
            ]
    except Exception as exc:
        print("validation failed: {0}".format(exc))
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
