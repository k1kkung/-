"""SOUP.AI local desktop backend.

The desktop window is created by pywebview and the local model is served by
llama.cpp's llama-server.exe. The frontend talks to this module through
pywebview's JavaScript bridge; no localhost web framework is required.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from story_repository import StoryDatabase
except ImportError:  # pragma: no cover - supports package-style imports
    from backend.story_repository import StoryDatabase

try:
    import requests
except Exception:  # pragma: no cover - handled as rule-mode fallback
    requests = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parent
MODEL_PATH = (
    PROJECT_ROOT
    / "models"
    / "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
)
EXPECTED_MODEL_SIZE = 2497281120
RUNTIME_EXE = PROJECT_ROOT / "runtime" / "llama-server.exe"
STORIES_FILE = BACKEND_DIR / "stories.json"
STORIES_DB_FILE = BACKEND_DIR / "stories.db"
CACHE_DIR = PROJECT_ROOT / "cache"
LOGS_DIR = PROJECT_ROOT / "logs"
APP_LOG_FILE = LOGS_DIR / "soup-ai.log"
LLAMA_LOG_FILE = LOGS_DIR / "llama-server.log"
INDEX_FILE = PROJECT_ROOT / "index.html"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 11435
DEFAULT_CTX_SIZE = 4096
DEFAULT_GPU_LAYERS = 99
DEFAULT_STARTUP_TIMEOUT = 240.0
DEFAULT_REQUEST_TIMEOUT = 30.0
DEFAULT_MIN_CONFIDENCE = 0.65

LOGGER = logging.getLogger("soup-ai")
_LOGGING_CONFIGURED = False


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def ensure_project_dirs() -> None:
    for directory in (
        CACHE_DIR,
        CACHE_DIR / "pip",
        CACHE_DIR / "temp",
        CACHE_DIR / "webview",
        CACHE_DIR / "python-pycache",
        LOGS_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def configure_environment() -> None:
    """Keep caches and temporary files under the project directory."""

    ensure_project_dirs()
    if hasattr(sys, "pycache_prefix") and not sys.pycache_prefix:
        sys.pycache_prefix = str(CACHE_DIR / "python-pycache")
    defaults = {
        "TEMP": CACHE_DIR / "temp",
        "TMP": CACHE_DIR / "temp",
        "PIP_CACHE_DIR": CACHE_DIR / "pip",
        "PYTHONPYCACHEPREFIX": CACHE_DIR / "python-pycache",
        "WEBVIEW2_USER_DATA_FOLDER": CACHE_DIR / "webview",
        "HF_HOME": CACHE_DIR / "huggingface",
        "XDG_CACHE_HOME": CACHE_DIR / "xdg",
    }
    for name, value in defaults.items():
        os.environ.setdefault(name, str(value))
        Path(os.environ[name]).mkdir(parents=True, exist_ok=True)


def configure_logging() -> None:
    global _LOGGING_CONFIGURED

    if _LOGGING_CONFIGURED:
        return

    ensure_project_dirs()
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    file_handler = logging.FileHandler(
        APP_LOG_FILE,
        encoding="utf-8",
        errors="replace",
    )
    file_handler.setFormatter(formatter)

    LOGGER.addHandler(file_handler)
    if sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        LOGGER.addHandler(stream_handler)
    _LOGGING_CONFIGURED = True


def _human_path(path: Path) -> str:
    return str(path)


def _read_stories(path: Path = STORIES_FILE) -> Dict[str, Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    if isinstance(raw, dict):
        stories_raw = raw.get("stories", [])
    else:
        stories_raw = raw

    if not isinstance(stories_raw, list):
        raise ValueError("stories.json must contain a list or a stories list")

    stories: Dict[str, Dict[str, Any]] = {}
    for story_raw in stories_raw:
        if not isinstance(story_raw, dict):
            raise ValueError("each story must be a JSON object")

        story_id = str(story_raw.get("id", "")).strip()
        if not story_id:
            raise ValueError("story id is required")
        if story_id in stories:
            raise ValueError("duplicate story id: {0}".format(story_id))

        facts_raw = story_raw.get("facts", [])
        if not isinstance(facts_raw, list) or not facts_raw:
            raise ValueError("story {0} has no facts".format(story_id))

        facts: Dict[str, Dict[str, Any]] = {}
        for fact_raw in facts_raw:
            if not isinstance(fact_raw, dict):
                raise ValueError("fact must be a JSON object")
            fact_id = str(fact_raw.get("id", "")).strip()
            if not fact_id or fact_id in facts:
                raise ValueError(
                    "story {0} has an invalid fact id".format(story_id)
                )
            if not isinstance(fact_raw.get("truth"), bool):
                raise ValueError(
                    "fact {0} must have a boolean truth".format(fact_id)
                )
            aliases = fact_raw.get("aliases", [])
            if not isinstance(aliases, list):
                aliases = []
            facts[fact_id] = {
                "id": fact_id,
                "description": str(
                    fact_raw.get("description", "")
                ).strip(),
                "truth": fact_raw["truth"],
                "aliases": [str(alias) for alias in aliases],
            }

        hints_raw = story_raw.get("hints", [])
        if not isinstance(hints_raw, list):
            hints_raw = []

        stories[story_id] = {
            "id": story_id,
            "surface": str(story_raw.get("surface", "")).strip(),
            "bottom": str(story_raw.get("bottom", "")).strip(),
            "facts": facts,
            "hints": [str(hint) for hint in hints_raw],
        }

    return stories


class LlamaServerManager:
    """Own the llama-server process for the lifetime of the desktop app."""

    def __init__(self) -> None:
        self.host = os.environ.get("SOUP_AI_HOST", DEFAULT_HOST)
        self.port = _env_int("SOUP_AI_PORT", DEFAULT_PORT)
        self.ctx_size = _env_int("SOUP_AI_CTX_SIZE", DEFAULT_CTX_SIZE)
        self.gpu_layers = _env_int(
            "SOUP_AI_GPU_LAYERS", DEFAULT_GPU_LAYERS
        )
        self.startup_timeout = _env_float(
            "SOUP_AI_STARTUP_TIMEOUT", DEFAULT_STARTUP_TIMEOUT
        )
        self.base_url = "http://{0}:{1}".format(self.host, self.port)
        self.process: Optional[subprocess.Popen] = None
        self.log_handle: Optional[Any] = None
        self.ready = False
        self.external_server = False
        self.startup_attempted = False
        self._lock = threading.RLock()

    def missing_requirements(self) -> List[str]:
        missing: List[str] = []
        if requests is None:
            missing.append("Python requests package is not installed")
        if not RUNTIME_EXE.is_file():
            missing.append(
                "llama-server.exe is missing: {0}".format(
                    _human_path(RUNTIME_EXE)
                )
            )
        if not MODEL_PATH.is_file():
            missing.append(
                "GGUF model is missing: {0}".format(_human_path(MODEL_PATH))
            )
        return missing

    def _model_size_warning(self) -> None:
        try:
            actual_size = MODEL_PATH.stat().st_size
        except OSError:
            return
        if actual_size != EXPECTED_MODEL_SIZE:
            LOGGER.warning(
                "Model size differs from expected: actual=%s expected=%s",
                actual_size,
                EXPECTED_MODEL_SIZE,
            )

    def _health_check(self) -> bool:
        if requests is None:
            return False
        try:
            response = requests.get(
                self.base_url + "/health",
                timeout=2.0,
            )
            return 200 <= response.status_code < 300
        except Exception:
            return False

    def start(self) -> bool:
        with self._lock:
            self.startup_attempted = True
            self.ready = False
            self.external_server = False

            missing = self.missing_requirements()
            if missing:
                for item in missing:
                    LOGGER.error(item)
                return False

            self._model_size_warning()
            if self._health_check():
                self.ready = True
                self.external_server = True
                LOGGER.info(
                    "Detected an existing llama-server at %s",
                    self.base_url,
                )
                return True

            command = [
                _human_path(RUNTIME_EXE),
                "-m",
                _human_path(MODEL_PATH),
                "--host",
                self.host,
                "--port",
                str(self.port),
                "--ctx-size",
                str(self.ctx_size),
                "--n-gpu-layers",
                str(self.gpu_layers),
            ]
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            try:
                self.log_handle = LLAMA_LOG_FILE.open(
                    "a",
                    encoding="utf-8",
                    errors="replace",
                )
                self.log_handle.write(
                    "\n--- starting llama-server at {0} ---\n".format(
                        time.strftime("%Y-%m-%d %H:%M:%S")
                    )
                )
                self.log_handle.flush()
                self.process = subprocess.Popen(
                    command,
                    cwd=str(PROJECT_ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=self.log_handle,
                    stderr=subprocess.STDOUT,
                    creationflags=creation_flags,
                )
            except Exception:
                LOGGER.exception("Unable to start llama-server")
                self.stop()
                return False

            deadline = time.monotonic() + self.startup_timeout
            while time.monotonic() < deadline:
                if self._health_check():
                    self.ready = True
                    LOGGER.info(
                        "llama-server is ready at %s", self.base_url
                    )
                    return True

                return_code = self.process.poll()
                if return_code is not None:
                    LOGGER.error(
                        "llama-server exited during startup with code %s",
                        return_code,
                    )
                    self.stop()
                    return False
                time.sleep(0.7)

            LOGGER.error(
                "Timed out waiting for llama-server health check"
            )
            self.stop()
            return False

    def status(self) -> str:
        with self._lock:
            if self.ready and self.external_server:
                return "ready"
            if (
                self.ready
                and self.process is not None
                and self.process.poll() is None
            ):
                return "ready"
            return "rules"

    def stop(self) -> None:
        with self._lock:
            process = self.process
            self.process = None
            self.ready = False
            self.external_server = False

            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=3.0)
                    except subprocess.TimeoutExpired:
                        LOGGER.warning(
                            "llama-server did not exit after kill"
                        )
                except Exception:
                    LOGGER.exception("Unable to stop llama-server cleanly")

            if self.log_handle is not None:
                try:
                    self.log_handle.flush()
                    self.log_handle.close()
                except Exception:
                    pass
                self.log_handle = None

    def shutdown(self) -> None:
        self.stop()


class LocalJudgeService:
    """pywebview JavaScript API and rule-enforced model mapper."""

    def __init__(self) -> None:
        self.stories: Dict[str, Dict[str, Any]] = {}
        self.db = StoryDatabase(STORIES_FILE, STORIES_DB_FILE)
        self.llama = LlamaServerManager()
        self.request_timeout = _env_float(
            "SOUP_AI_REQUEST_TIMEOUT", DEFAULT_REQUEST_TIMEOUT
        )
        self.min_confidence = _env_float(
            "SOUP_AI_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE
        )

    def start(self) -> bool:
        try:
            self.db.initialize()
            self.stories = {}
            LOGGER.info("Loaded %s stories", self.db.story_count)
        except Exception:
            LOGGER.exception("Unable to initialize story database")
            self.stories = {}
            return False

        if self.db.story_count <= 0:
            LOGGER.error("No stories are available")
            return False

        return self.llama.start()

    def shutdown(self) -> None:
        self.llama.shutdown()

    def get_ai_status(self) -> str:
        status = self.llama.status()
        LOGGER.info("AI status requested by desktop UI: %s", status)
        return status

    def get_runtime_info(self) -> Dict[str, Any]:
        return {
            "status": self.llama.status(),
            "model_exists": MODEL_PATH.is_file(),
            "model_size": (
                MODEL_PATH.stat().st_size if MODEL_PATH.is_file() else None
            ),
            "runtime_exists": RUNTIME_EXE.is_file(),
            "story_count": self.db.story_count,
            "endpoint": self.llama.base_url,
        }

    def get_catalog(self) -> Dict[str, Any]:
        return self.db.catalog()

    def get_preferences(self) -> Dict[str, Any]:
        return self.db.get_preferences()

    def save_preferences(self, preferences: Any) -> bool:
        try:
            self.db.save_preferences(preferences)
            return True
        except Exception:
            LOGGER.exception("Unable to save preferences")
            return False

    def clear_preferences(self) -> bool:
        try:
            self.db.clear_preferences()
            return True
        except Exception:
            LOGGER.exception("Unable to clear preferences")
            return False

    def search_stories(
        self,
        query: Any = "",
        filters: Any = None,
        page: Any = 1,
        page_size: Any = 12,
    ) -> Dict[str, Any]:
        try:
            return self.db.search_stories(
                str(query or ""),
                filters if isinstance(filters, dict) else {},
                int(page or 1),
                int(page_size or 12),
            )
        except Exception:
            LOGGER.exception("Unable to search stories")
            return {
                "items": [],
                "page": 1,
                "page_size": 12,
                "total": 0,
                "page_count": 1,
            }

    def draw_story(self, filters: Any = None) -> Optional[Dict[str, Any]]:
        try:
            return self.db.draw_story(
                filters if isinstance(filters, dict) else {}
            )
        except Exception:
            LOGGER.exception("Unable to draw a story")
            return None

    def get_story(self, story_id: Any) -> Optional[Dict[str, Any]]:
        return self.db.get_public_story(str(story_id or "").strip())

    def get_reveal(self, story_id: Any) -> Optional[Dict[str, Any]]:
        return self.db.get_reveal(str(story_id or "").strip())

    def mark_disliked(self, story_id: Any) -> bool:
        return self.db.mark_disliked(str(story_id or "").strip())

    def get_hint(
        self,
        story_id: Any,
        hints_used: Any = 0,
        use_ai: Any = True,
    ) -> Optional[Dict[str, Any]]:
        story_key = str(story_id or "").strip()
        story = self.db.get_judge_story(story_key)
        if story is None:
            return None

        used = max(0, int(hints_used or 0))
        if used >= 2:
            return None

        if bool(use_ai) and self.llama.status() == "ready":
            generated = self._request_ai_hint(story, used)
            if generated:
                return {
                    "hint": generated,
                    "hint_index": used,
                    "used": used + 1,
                    "max": 2,
                    "source": "ai",
                }

        return self.db.get_static_hint(story_key, used)

    def judge(self, story_id: Any, question: Any) -> Optional[str]:
        """Return yes/no/irrelevant, or None when the JS bridge should fallback."""

        if self.llama.status() != "ready":
            return None

        story_key = str(story_id or "").strip()
        question_text = str(question or "").strip()
        if (
            not story_key
            or not question_text
            or len(question_text) > 300
        ):
            return None

        story = self.db.get_judge_story(story_key)
        if story is None:
            return None

        try:
            parsed = self._judge_with_model(story, question_text)
        except Exception:
            LOGGER.exception("AI judge request failed")
            return None

        if parsed is None:
            return None

        answer, fact_id, confidence = parsed
        if confidence < self.min_confidence:
            LOGGER.info(
                "AI confidence below threshold: story=%s fact=%s "
                "confidence=%s",
                story_key,
                fact_id,
                confidence,
            )
            return None

        if answer not in ("yes", "no", "irrelevant"):
            return None

        LOGGER.info(
            "AI verdict: story=%s fact=%s confidence=%s answer=%s",
            story_key,
            fact_id,
            confidence,
            answer,
        )
        return answer

    def _judge_with_model(
        self,
        story: Dict[str, Any],
        question: str,
    ) -> Optional[Tuple[str, Optional[str], float]]:
        prompt = self._build_system_prompt(story)
        content = self._request_completion(prompt, question)
        if not content:
            return None
        return self._parse_model_result(content, story)

    def _request_ai_hint(
        self,
        story: Dict[str, Any],
        hints_used: int,
    ) -> Optional[str]:
        facts = []
        for fact in story["facts"].values():
            facts.append(
                {
                    "id": fact["id"],
                    "description": fact["description"],
                    "aliases": fact["aliases"],
                }
            )
        prompt = (
            "你是海龟汤的提示生成器。只允许使用下面事实表中的信息，"
            "不能解释汤底，不能直接说出事实结论，不能复述汤底。"
            "请生成一句含蓄、能帮助玩家继续提问的中文提示，"
            "不要包含答案、判定词或 JSON 之外的内容。"
            '严格输出 JSON：{"hint":"..."}\n'
            "【公开汤面】\n"
            + story.get("surface", "")
            + "\n【事实表】\n"
            + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
        )
        content = self._request_completion(
            prompt,
            "请生成第 {0} 条提示。".format(hints_used + 1),
        )
        if not content:
            return None
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except ValueError:
            return None
        hint = str(data.get("hint", "")).strip()
        if not hint or len(hint) > 120:
            return None
        if story.get("bottom", "") and story["bottom"] in hint:
            return None
        for fact in story["facts"].values():
            if hint == fact["description"]:
                return None
        return hint

    def _build_system_prompt(self, story: Dict[str, Any]) -> str:
        facts = []
        for fact in story["facts"].values():
            facts.append(
                {
                    "id": fact["id"],
                    "description": fact["description"],
                    "truth": fact["truth"],
                    "aliases": fact["aliases"],
                }
            )

        facts_json = json.dumps(
            facts,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return (
            "你是海龟汤裁判的问答映射器，不是汤底解释器。\n"
            "你的唯一任务：把玩家问题映射到下面事实表中的一条事实。\n"
            "事实表是唯一裁决依据。不得自由解释汤底，不得泄露事实，"
            "不得补充事实表之外的信息。\n"
            "如果问题无法可靠映射到事实，返回 irrelevant。\n"
            "输出必须是一个严格 JSON 对象，不要 Markdown，不要解释，"
            "不要输出 JSON 之外的任何文字。\n"
            '固定格式：{"verdict":"yes","fact_id":"...","confidence":0.95}\n'
            "verdict 只能是 yes、no、irrelevant。\n"
            "fact_id 必须是事实表里的 id，无法映射时使用 null。\n"
            "confidence 是 0 到 1 之间的数字。\n"
            "即使事实表里某条事实的 truth 与你的直觉不同，也必须按"
            "该事实的 truth 映射；后端会根据 fact_id 的真值决定最终"
            "回答。\n"
            "【公开汤面】\n"
            + story.get("surface", "")
            + "\n【事实表】\n"
            + facts_json
        )

    def _request_completion(
        self,
        system_prompt: str,
        question: str,
    ) -> Optional[str]:
        if requests is None:
            return None

        payload: Dict[str, Any] = {
            "model": MODEL_PATH.stem,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
            "temperature": 0.0,
            "top_p": 0.1,
            "max_tokens": 128,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        data = self._post_chat(payload)
        if data is None:
            return None

        try:
            choices = data.get("choices", [])
            if not choices:
                return None
            message = choices[0].get("message", {})
            content = message.get("content", "")
            if isinstance(content, dict):
                return json.dumps(content, ensure_ascii=False)
            return str(content).strip()
        except Exception:
            LOGGER.exception("Unexpected llama-server response shape")
            return None

    def _post_chat(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if requests is None:
            return None

        url = self.llama.base_url + "/v1/chat/completions"
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self.request_timeout,
            )
        except requests.RequestException:
            LOGGER.warning("llama-server request failed")
            return None

        # Older llama.cpp builds may reject response_format. Retry once
        # without it; the parser still enforces strict JSON.
        if response.status_code >= 400 and "response_format" in payload:
            retry_payload = dict(payload)
            retry_payload.pop("response_format", None)
            try:
                response = requests.post(
                    url,
                    json=retry_payload,
                    timeout=self.request_timeout,
                )
            except requests.RequestException:
                LOGGER.warning("llama-server retry failed")
                return None

        if not 200 <= response.status_code < 300:
            LOGGER.warning(
                "llama-server returned HTTP %s", response.status_code
            )
            return None

        try:
            data = response.json()
        except ValueError:
            LOGGER.warning("llama-server returned non-JSON response")
            return None
        return data if isinstance(data, dict) else None

    def _parse_model_result(
        self,
        content: str,
        story: Dict[str, Any],
    ) -> Optional[Tuple[str, Optional[str], float]]:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            return None

        try:
            data = json.loads(match.group(0))
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None

        verdict = str(data.get("verdict", "")).strip().lower()
        if verdict not in ("yes", "no", "irrelevant"):
            return None

        raw_fact_id = data.get("fact_id", data.get("factId"))
        fact_id: Optional[str] = None
        if raw_fact_id is not None:
            fact_id = str(raw_fact_id).strip()
            if fact_id.lower() in ("", "null", "none"):
                fact_id = None

        try:
            confidence = float(data.get("confidence"))
        except (TypeError, ValueError):
            return None
        if confidence < 0.0 or confidence > 1.0:
            return None

        if verdict == "irrelevant":
            return "irrelevant", None, confidence

        if fact_id is None or fact_id not in story["facts"]:
            return None

        fact = story["facts"][fact_id]
        answer = "yes" if fact["truth"] else "no"
        return answer, fact_id, confidence


def run_self_check() -> int:
    configure_environment()
    configure_logging()

    report: Dict[str, Any] = {
        "project_root": _human_path(PROJECT_ROOT),
        "python": sys.version.split()[0],
        "runtime_exists": RUNTIME_EXE.is_file(),
        "runtime_path": _human_path(RUNTIME_EXE),
        "model_exists": MODEL_PATH.is_file(),
        "model_path": _human_path(MODEL_PATH),
        "model_size": None,
        "expected_model_size": EXPECTED_MODEL_SIZE,
        "stories": {},
    }
    if MODEL_PATH.is_file():
        report["model_size"] = MODEL_PATH.stat().st_size

    try:
        database = StoryDatabase(STORIES_FILE, STORIES_DB_FILE)
        database.initialize()
        report["stories"] = database.validate_current_seed()
        report["stories"]["sample_ids"] = [
            row["id"]
            for row in database.search_stories(page_size=3)["items"]
        ]
    except Exception as exc:
        report["stories_error"] = str(exc)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["stories"].get("story_count") else 1


def main() -> int:
    configure_environment()
    configure_logging()

    if "--check" in sys.argv:
        return run_self_check()

    try:
        service = LocalJudgeService()
        service.start()
        atexit.register(service.shutdown)

        try:
            import webview
        except Exception:
            LOGGER.exception("pywebview is not available")
            service.shutdown()
            return 1

        webview.settings["ALLOW_FILE_URLS"] = True
        window = webview.create_window(
            "SOUP.AI 海龟汤",
            url=INDEX_FILE.as_uri(),
            js_api=service,
            width=1180,
            height=820,
            min_size=(900, 620),
            background_color="#f1ece5",
        )
        window.events.closed += service.shutdown

        def on_started() -> None:
            close_after = _env_float("SOUP_AI_AUTOCLOSE_SECONDS", 0.0)
            if close_after > 0:
                threading.Timer(close_after, window.destroy).start()

        webview.start(
            func=on_started,
            gui="edgechromium",
            debug=os.environ.get("SOUP_AI_DEBUG") == "1",
            private_mode=False,
            storage_path=str(CACHE_DIR / "webview"),
        )
        return 0
    except Exception:
        LOGGER.exception("Desktop app startup failed")
        return 1
    finally:
        try:
            service.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
