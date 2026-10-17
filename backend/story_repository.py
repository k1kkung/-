"""SQLite-backed story catalog for SOUP.AI.

The seed JSON is the editable content source. The SQLite file is generated
from it at startup and stores local preferences such as seen and disliked
stories. The frontend never needs direct database access.
"""

from __future__ import annotations

import json
import random
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SCHEMA_VERSION = 1
DEFAULT_GENRES = [
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
DEFAULT_DIFFICULTIES = ["入门", "进阶", "烧脑"]
DEFAULT_SCALES = ["无怖", "惊悚", "重口"]
DEFAULT_PAGE_SIZE = 12


class SeedError(ValueError):
    """Raised when the editable seed file is invalid."""


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_json(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class StoryDatabase:
    def __init__(self, seed_path: Path, db_path: Path) -> None:
        self.seed_path = Path(seed_path)
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self.genres: List[str] = list(DEFAULT_GENRES)
        self.difficulties: List[str] = list(DEFAULT_DIFFICULTIES)
        self.scales: List[str] = list(DEFAULT_SCALES)
        self.story_count = 0

    def initialize(self) -> None:
        raw = self._read_seed()
        normalized = self._normalize_seed(raw)
        self._ensure_schema()
        self._sync_seed(normalized)
        self.genres = normalized["genres"]
        self.difficulties = normalized["difficulties"]
        self.scales = normalized["scales"]
        self.story_count = len(normalized["stories"])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    def _read_seed(self) -> Any:
        with self.seed_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _normalize_seed(self, raw: Any) -> Dict[str, Any]:
        if isinstance(raw, list):
            stories_raw = raw
            raw = {}
        elif isinstance(raw, dict):
            stories_raw = raw.get("stories")
        else:
            raise SeedError("stories.json must contain an object or list")

        if not isinstance(stories_raw, list):
            raise SeedError("stories.json must contain a stories list")

        genres = _as_list(raw.get("genres")) or list(DEFAULT_GENRES)
        difficulties = _as_list(raw.get("difficulties")) or list(
            DEFAULT_DIFFICULTIES
        )
        scales = _as_list(raw.get("scales")) or list(DEFAULT_SCALES)

        if len(genres) != 10:
            raise SeedError("exactly ten genres are required")
        if len(difficulties) != 3:
            raise SeedError("exactly three difficulty levels are required")
        if len(scales) != 3:
            raise SeedError("exactly three scale levels are required")

        stories: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, story_raw in enumerate(stories_raw):
            if not isinstance(story_raw, dict):
                raise SeedError("story {0} is not an object".format(index))
            story = self._normalize_story(
                story_raw,
                genres,
                difficulties,
                scales,
                index,
            )
            if story["id"] in seen_ids:
                raise SeedError(
                    "duplicate story id: {0}".format(story["id"])
                )
            seen_ids.add(story["id"])
            stories.append(story)

        if not stories:
            raise SeedError("at least one story is required")

        return {
            "schema_version": int(raw.get("schema_version", SCHEMA_VERSION)),
            "genres": genres,
            "difficulties": difficulties,
            "scales": scales,
            "stories": stories,
        }

    def _normalize_story(
        self,
        raw: Dict[str, Any],
        genres: Sequence[str],
        difficulties: Sequence[str],
        scales: Sequence[str],
        index: int,
    ) -> Dict[str, Any]:
        story_id = str(raw.get("id", "")).strip()
        if not story_id:
            raise SeedError("story {0} has no id".format(index))

        title = str(raw.get("title", "")).strip()
        surface = str(raw.get("surface", "")).strip()
        bottom = str(raw.get("bottom", "")).strip()
        if not title or not surface or not bottom:
            raise SeedError(
                "story {0} needs title, surface and bottom".format(story_id)
            )

        primary_genre = str(
            raw.get("primary_genre") or raw.get("genre") or ""
        ).strip()
        if primary_genre not in genres:
            raise SeedError(
                "story {0} has unknown primary genre {1}".format(
                    story_id, primary_genre
                )
            )

        difficulty = str(
            raw.get("difficulty") or DEFAULT_DIFFICULTIES[0]
        ).strip()
        if difficulty not in difficulties:
            raise SeedError(
                "story {0} has unknown difficulty {1}".format(
                    story_id, difficulty
                )
            )

        scale = str(raw.get("scale") or DEFAULT_SCALES[0]).strip()
        if scale not in scales:
            raise SeedError(
                "story {0} has unknown scale {1}".format(story_id, scale)
            )

        secondary_genres = [
            genre
            for genre in _as_list(
                raw.get("secondary_genres") or raw.get("genres")
            )
            if genre in genres
        ]
        all_genres = []
        for genre in [primary_genre] + secondary_genres:
            if genre not in all_genres:
                all_genres.append(genre)

        facts_raw = raw.get("facts") or []
        if isinstance(facts_raw, dict):
            facts_raw = [
                dict(value, id=key)
                for key, value in facts_raw.items()
            ]
        if not isinstance(facts_raw, list) or len(facts_raw) < 4:
            raise SeedError(
                "story {0} needs at least four facts".format(story_id)
            )

        facts: List[Dict[str, Any]] = []
        fact_ids: set[str] = set()
        for fact_raw in facts_raw:
            if not isinstance(fact_raw, dict):
                raise SeedError(
                    "story {0} contains an invalid fact".format(story_id)
                )
            fact_id = str(fact_raw.get("id", "")).strip()
            description = str(
                fact_raw.get("description", "")
            ).strip()
            if not fact_id or not description:
                raise SeedError(
                    "story {0} contains an incomplete fact".format(story_id)
                )
            if fact_id in fact_ids:
                raise SeedError(
                    "story {0} has duplicate fact {1}".format(
                        story_id, fact_id
                    )
                )
            if not isinstance(fact_raw.get("truth"), bool):
                raise SeedError(
                    "fact {0} needs a boolean truth".format(fact_id)
                )
            aliases = _as_list(fact_raw.get("aliases"))
            if not aliases:
                raise SeedError(
                    "fact {0} needs at least one alias".format(fact_id)
                )
            fact_ids.add(fact_id)
            facts.append(
                {
                    "id": fact_id,
                    "description": description,
                    "truth": fact_raw["truth"],
                    "aliases": aliases,
                }
            )

        hints = _as_list(raw.get("hints"))
        suggestions = _as_list(raw.get("suggestions"))
        if len(hints) < 2:
            raise SeedError(
                "story {0} needs at least two hints".format(story_id)
            )
        if len(suggestions) < 3:
            raise SeedError(
                "story {0} needs at least three suggestions".format(
                    story_id
                )
            )

        warnings = _as_list(raw.get("warnings"))
        if scale == "重口":
            warnings.append("包含犯罪、死亡或心理恐怖等主题")
        warnings = list(dict.fromkeys(warnings))

        return {
            "id": story_id,
            "title": title,
            "surface": surface,
            "bottom": bottom,
            "primary_genre": primary_genre,
            "secondary_genres": secondary_genres,
            "genres": all_genres,
            "tags": _as_list(raw.get("tags")),
            "difficulty": difficulty,
            "scale": scale,
            "warnings": warnings,
            "facts": facts,
            "hints": hints,
            "suggestions": suggestions,
        }

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            connection = self._connect()
            try:
                connection.executescript(
                    """
                    PRAGMA journal_mode=WAL;
                    CREATE TABLE IF NOT EXISTS stories (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        surface TEXT NOT NULL,
                        bottom TEXT NOT NULL,
                        primary_genre TEXT NOT NULL,
                        difficulty TEXT NOT NULL,
                        scale TEXT NOT NULL,
                        warnings_json TEXT NOT NULL DEFAULT '[]',
                        active INTEGER NOT NULL DEFAULT 1
                    );
                    CREATE TABLE IF NOT EXISTS story_genres (
                        story_id TEXT NOT NULL,
                        genre TEXT NOT NULL,
                        PRIMARY KEY (story_id, genre)
                    );
                    CREATE TABLE IF NOT EXISTS story_tags (
                        story_id TEXT NOT NULL,
                        tag TEXT NOT NULL,
                        PRIMARY KEY (story_id, tag)
                    );
                    CREATE TABLE IF NOT EXISTS story_facts (
                        story_id TEXT NOT NULL,
                        fact_id TEXT NOT NULL,
                        description TEXT NOT NULL,
                        truth INTEGER NOT NULL,
                        aliases_json TEXT NOT NULL DEFAULT '[]',
                        PRIMARY KEY (story_id, fact_id)
                    );
                    CREATE TABLE IF NOT EXISTS story_hints (
                        story_id TEXT NOT NULL,
                        ordinal INTEGER NOT NULL,
                        hint TEXT NOT NULL,
                        PRIMARY KEY (story_id, ordinal)
                    );
                    CREATE TABLE IF NOT EXISTS story_suggestions (
                        story_id TEXT NOT NULL,
                        ordinal INTEGER NOT NULL,
                        suggestion TEXT NOT NULL,
                        PRIMARY KEY (story_id, ordinal)
                    );
                    CREATE TABLE IF NOT EXISTS story_preferences (
                        story_id TEXT PRIMARY KEY,
                        seen_count INTEGER NOT NULL DEFAULT 0,
                        last_seen_at TEXT,
                        disliked_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_stories_genre
                        ON stories(primary_genre);
                    CREATE INDEX IF NOT EXISTS idx_stories_filters
                        ON stories(difficulty, scale, active);
                    CREATE INDEX IF NOT EXISTS idx_story_genres_genre
                        ON story_genres(genre);
                    """
                )
                connection.commit()
            finally:
                connection.close()

    def _sync_seed(self, seed: Dict[str, Any]) -> None:
        stories = seed["stories"]
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN")
                connection.execute("DELETE FROM story_genres")
                connection.execute("DELETE FROM story_tags")
                connection.execute("DELETE FROM story_facts")
                connection.execute("DELETE FROM story_hints")
                connection.execute("DELETE FROM story_suggestions")
                connection.execute("DELETE FROM stories")

                for story in stories:
                    connection.execute(
                        """
                        INSERT INTO stories (
                            id, title, surface, bottom, primary_genre,
                            difficulty, scale, warnings_json, active
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                        """,
                        (
                            story["id"],
                            story["title"],
                            story["surface"],
                            story["bottom"],
                            story["primary_genre"],
                            story["difficulty"],
                            story["scale"],
                            _json(story["warnings"]),
                        ),
                    )
                    connection.executemany(
                        """
                        INSERT INTO story_genres (story_id, genre)
                        VALUES (?, ?)
                        """,
                        [
                            (story["id"], genre)
                            for genre in story["genres"]
                        ],
                    )
                    connection.executemany(
                        """
                        INSERT INTO story_tags (story_id, tag)
                        VALUES (?, ?)
                        """,
                        [
                            (story["id"], tag)
                            for tag in story["tags"]
                        ],
                    )
                    connection.executemany(
                        """
                        INSERT INTO story_facts (
                            story_id, fact_id, description, truth,
                            aliases_json
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                story["id"],
                                fact["id"],
                                fact["description"],
                                1 if fact["truth"] else 0,
                                _json(fact["aliases"]),
                            )
                            for fact in story["facts"]
                        ],
                    )
                    connection.executemany(
                        """
                        INSERT INTO story_hints (story_id, ordinal, hint)
                        VALUES (?, ?, ?)
                        """,
                        [
                            (story["id"], index, hint)
                            for index, hint in enumerate(story["hints"])
                        ],
                    )
                    connection.executemany(
                        """
                        INSERT INTO story_suggestions (
                            story_id, ordinal, suggestion
                        ) VALUES (?, ?, ?)
                        """,
                        [
                            (story["id"], index, suggestion)
                            for index, suggestion in enumerate(
                                story["suggestions"]
                            )
                        ],
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def catalog(self) -> Dict[str, Any]:
        with self._connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM stories WHERE active = 1"
            ).fetchone()["count"]
            disliked = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM story_preferences
                WHERE disliked_at IS NOT NULL
                """
            ).fetchone()["count"]
        return {
            "genres": list(self.genres),
            "difficulties": list(self.difficulties),
            "scales": list(self.scales),
            "story_count": count,
            "disliked_count": disliked,
        }

    def _story_filters(
        self,
        filters: Optional[Dict[str, Any]],
    ) -> Tuple[List[str], List[Any], str]:
        filters = filters or {}
        clauses: List[str] = ["s.active = 1"]
        params: List[Any] = []

        genres = _as_list(
            filters.get("genres") or filters.get("genre")
        )
        if genres:
            placeholders = ",".join("?" for _ in genres)
            clauses.append(
                """
                EXISTS (
                    SELECT 1 FROM story_genres g
                    WHERE g.story_id = s.id
                      AND g.genre IN ({0})
                )
                """.format(placeholders)
            )
            params.extend(genres)

        difficulties = _as_list(
            filters.get("difficulties") or filters.get("difficulty")
        )
        if difficulties:
            placeholders = ",".join("?" for _ in difficulties)
            clauses.append("s.difficulty IN ({0})".format(placeholders))
            params.extend(difficulties)

        scales = _as_list(filters.get("scales") or filters.get("scale"))
        if scales:
            placeholders = ",".join("?" for _ in scales)
            clauses.append("s.scale IN ({0})".format(placeholders))
            params.extend(scales)

        query = str(filters.get("query") or filters.get("q") or "").strip()
        if query:
            like = "%{0}%".format(query)
            clauses.append(
                """
                (
                    s.title LIKE ? OR s.surface LIKE ? OR
                    EXISTS (
                        SELECT 1 FROM story_tags t
                        WHERE t.story_id = s.id AND t.tag LIKE ?
                    )
                )
                """
            )
            params.extend([like, like, like])

        return clauses, params, " AND ".join(clauses)

    def search_stories(
        self,
        query: str = "",
        filters: Optional[Dict[str, Any]] = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Dict[str, Any]:
        filters = dict(filters or {})
        if query:
            filters["query"] = query
        clauses, params, where = self._story_filters(filters)
        page = max(1, int(page or 1))
        page_size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), 60))
        offset = (page - 1) * page_size

        with self._connect() as connection:
            total = connection.execute(
                "SELECT COUNT(*) AS count FROM stories s WHERE {0}".format(
                    where
                ),
                params,
            ).fetchone()["count"]
            rows = connection.execute(
                """
                SELECT s.id, s.title, s.surface, s.primary_genre,
                       s.difficulty, s.scale, s.warnings_json,
                       COALESCE(p.seen_count, 0) AS seen_count,
                       p.disliked_at
                FROM stories s
                LEFT JOIN story_preferences p ON p.story_id = s.id
                WHERE {0}
                ORDER BY s.primary_genre, s.title
                LIMIT ? OFFSET ?
                """.format(where),
                params + [page_size, offset],
            ).fetchall()

        items = [
            self._public_from_row(row, connection=None)
            for row in rows
        ]
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "page_count": max(1, (total + page_size - 1) // page_size),
        }

    def _public_from_row(
        self,
        row: sqlite3.Row,
        connection: Optional[sqlite3.Connection],
    ) -> Dict[str, Any]:
        story_id = row["id"]
        if connection is None:
            with self._connect() as child_connection:
                genres = child_connection.execute(
                    """
                    SELECT genre FROM story_genres
                    WHERE story_id = ? ORDER BY genre
                    """,
                    (story_id,),
                ).fetchall()
                tags = child_connection.execute(
                    """
                    SELECT tag FROM story_tags
                    WHERE story_id = ? ORDER BY tag
                    """,
                    (story_id,),
                ).fetchall()
                hints = child_connection.execute(
                    """
                    SELECT hint FROM story_hints
                    WHERE story_id = ? ORDER BY ordinal
                    """,
                    (story_id,),
                ).fetchall()
                suggestions = child_connection.execute(
                    """
                    SELECT suggestion FROM story_suggestions
                    WHERE story_id = ? ORDER BY ordinal
                    """,
                    (story_id,),
                ).fetchall()
        else:
            genres = connection.execute(
                """
                SELECT genre FROM story_genres
                WHERE story_id = ? ORDER BY genre
                """,
                (story_id,),
            ).fetchall()
            tags = connection.execute(
                """
                SELECT tag FROM story_tags
                WHERE story_id = ? ORDER BY tag
                """,
                (story_id,),
            ).fetchall()
            hints = connection.execute(
                """
                SELECT hint FROM story_hints
                WHERE story_id = ? ORDER BY ordinal
                """,
                (story_id,),
            ).fetchall()
            suggestions = connection.execute(
                """
                SELECT suggestion FROM story_suggestions
                WHERE story_id = ? ORDER BY ordinal
                """,
                (story_id,),
            ).fetchall()

        return {
            "id": story_id,
            "title": row["title"],
            "surface": row["surface"],
            "primary_genre": row["primary_genre"],
            "genres": [item["genre"] for item in genres],
            "tags": [item["tag"] for item in tags],
            "difficulty": row["difficulty"],
            "scale": row["scale"],
            "warnings": _load_json(row["warnings_json"], []),
            "hints": [item["hint"] for item in hints],
            "suggestions": [
                item["suggestion"] for item in suggestions
            ],
            "seen_count": int(row["seen_count"] or 0),
            "is_disliked": bool(row["disliked_at"]),
        }

    def get_public_story(self, story_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.id, s.title, s.surface, s.primary_genre,
                       s.difficulty, s.scale, s.warnings_json,
                       COALESCE(p.seen_count, 0) AS seen_count,
                       p.disliked_at
                FROM stories s
                LEFT JOIN story_preferences p ON p.story_id = s.id
                WHERE s.id = ? AND s.active = 1
                """,
                (story_id,),
            ).fetchone()
            if row is None:
                return None
            return self._public_from_row(row, connection)

    def get_judge_story(self, story_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            story_row = connection.execute(
                """
                SELECT id, title, surface, bottom, primary_genre,
                       difficulty, scale
                FROM stories
                WHERE id = ? AND active = 1
                """,
                (story_id,),
            ).fetchone()
            if story_row is None:
                return None

            facts = connection.execute(
                """
                SELECT fact_id, description, truth, aliases_json
                FROM story_facts
                WHERE story_id = ?
                ORDER BY rowid
                """,
                (story_id,),
            ).fetchall()
            hints = connection.execute(
                """
                SELECT hint FROM story_hints
                WHERE story_id = ?
                ORDER BY ordinal
                """,
                (story_id,),
            ).fetchall()

        fact_map: Dict[str, Dict[str, Any]] = {}
        for row in facts:
            fact_map[row["fact_id"]] = {
                "id": row["fact_id"],
                "description": row["description"],
                "truth": bool(row["truth"]),
                "aliases": _load_json(row["aliases_json"], []),
            }
        return {
            "id": story_row["id"],
            "title": story_row["title"],
            "surface": story_row["surface"],
            "bottom": story_row["bottom"],
            "primary_genre": story_row["primary_genre"],
            "difficulty": story_row["difficulty"],
            "scale": story_row["scale"],
            "facts": fact_map,
            "hints": [row["hint"] for row in hints],
        }

    def get_reveal(self, story_id: str) -> Optional[Dict[str, Any]]:
        story = self.get_judge_story(story_id)
        if story is None:
            return None
        return {
            "id": story["id"],
            "title": story["title"],
            "bottom": story["bottom"],
            "facts": [
                {
                    "description": fact["description"],
                    "truth": fact["truth"],
                }
                for fact in story["facts"].values()
            ],
        }

    def _matching_candidates(
        self,
        filters: Optional[Dict[str, Any]],
        exclude_disliked: bool = True,
    ) -> List[sqlite3.Row]:
        clauses, params, where = self._story_filters(filters)
        if exclude_disliked:
            clauses.append("p.disliked_at IS NULL")
            where = " AND ".join(clauses)
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT s.id,
                       COALESCE(p.seen_count, 0) AS seen_count
                FROM stories s
                LEFT JOIN story_preferences p ON p.story_id = s.id
                WHERE {0}
                """.format(where),
                params,
            ).fetchall()

    def draw_story(
        self,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        candidates = self._matching_candidates(filters, True)
        if not candidates:
            return None
        minimum_seen = min(row["seen_count"] for row in candidates)
        first_pool = [
            row["id"]
            for row in candidates
            if row["seen_count"] == minimum_seen
        ]
        story_id = random.SystemRandom().choice(first_pool)
        self.mark_seen(story_id)
        return self.get_public_story(story_id)

    def mark_seen(self, story_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO story_preferences (
                    story_id, seen_count, last_seen_at, disliked_at
                ) VALUES (?, 1, CURRENT_TIMESTAMP, NULL)
                ON CONFLICT(story_id) DO UPDATE SET
                    seen_count = seen_count + 1,
                    last_seen_at = CURRENT_TIMESTAMP
                """,
                (story_id,),
            )
            connection.commit()

    def mark_disliked(self, story_id: str) -> bool:
        with self._lock, self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM stories WHERE id = ? AND active = 1",
                (story_id,),
            ).fetchone()
            if exists is None:
                return False
            connection.execute(
                """
                INSERT INTO story_preferences (
                    story_id, seen_count, last_seen_at, disliked_at
                ) VALUES (?, 0, NULL, CURRENT_TIMESTAMP)
                ON CONFLICT(story_id) DO UPDATE SET
                    disliked_at = CURRENT_TIMESTAMP
                """,
                (story_id,),
            )
            connection.commit()
        return True

    def get_preferences(self) -> Dict[str, Any]:
        default = {
            "genres": [],
            "difficulties": [],
            "scales": [],
            "ai_hint": True,
        }
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM app_settings WHERE key = 'preferences'"
            ).fetchone()
        if row is None:
            return default
        value = _load_json(row["value_json"], default)
        return value if isinstance(value, dict) else default

    def save_preferences(self, preferences: Optional[Dict[str, Any]]) -> None:
        preferences = preferences or {}
        allowed_genres = [
            item
            for item in _as_list(preferences.get("genres"))
            if item in self.genres
        ]
        allowed_difficulties = [
            item
            for item in _as_list(preferences.get("difficulties"))
            if item in self.difficulties
        ]
        allowed_scales = [
            item
            for item in _as_list(preferences.get("scales"))
            if item in self.scales
        ]
        cleaned = {
            "genres": allowed_genres,
            "difficulties": allowed_difficulties,
            "scales": allowed_scales,
            "ai_hint": bool(preferences.get("ai_hint", True)),
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO app_settings (key, value_json)
                VALUES ('preferences', ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                (_json(cleaned),),
            )
            connection.commit()

    def clear_preferences(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM story_preferences")
            connection.execute(
                "DELETE FROM app_settings WHERE key = 'preferences'"
            )
            connection.commit()

    def get_static_hint(
        self,
        story_id: str,
        hints_used: int,
    ) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ordinal, hint FROM story_hints
                WHERE story_id = ?
                ORDER BY ordinal
                """,
                (story_id,),
            ).fetchall()
        index = max(0, int(hints_used or 0))
        if index >= len(rows):
            return None
        return {
            "hint": rows[index]["hint"],
            "hint_index": index,
            "used": index + 1,
            "max": len(rows),
            "source": "static",
        }

    def validate_current_seed(self) -> Dict[str, Any]:
        normalized = self._normalize_seed(self._read_seed())
        return {
            "schema_version": normalized["schema_version"],
            "genre_count": len(normalized["genres"]),
            "difficulty_count": len(normalized["difficulties"]),
            "scale_count": len(normalized["scales"]),
            "story_count": len(normalized["stories"]),
        }
