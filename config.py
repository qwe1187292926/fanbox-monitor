"""配置加载：环境变量 + per-creator 规则。"""
from __future__ import annotations

import json
import os
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from i18n import SUPPORTED_LANGS, is_supported_lang, normalize_lang, t
from models.types import CreatorRule


DEFAULT_EXT_WHITELIST = [
    "jpg", "jpeg", "png", "gif", "bmp",
    "wav", "mp3", "flac",
    "mp4", "mov", "avi",
    "zip",
    "psd", "clip",
    "pdf",
]


@dataclass
class Settings:
    # 鉴权 & 网络
    session: str
    user_agent: str
    proxy: Optional[str]

    # 路径
    download_dir: Path
    db_path: Path
    log_level: str

    # 模式开关
    mode_supporting: bool
    mode_following: bool

    # 限速 & 并发
    interval_sec: float
    concurrency: int

    # 过滤
    ext_whitelist: set[str]
    fee_min: int
    fee_max: Optional[int]
    date_after: Optional[str]  # ISO 8601

    # 命名 & 通知 & 冷启动 & 重试
    name_rule: str
    notify_min_new: int
    first_run_max_posts: int
    post_403_retries: int
    post_403_backoff_base: float
    forbidden_fee_infer_threshold: int
    run_lock_ttl_sec: int

    # Bark 通知（可选）。设了 device_key 就额外走 Bark per-creator 通知（带头像）。
    bark_server: str
    bark_device_key: str
    bark_group: str
    bark_sound: str

    # per-creator
    lang: str = "zh-CN"
    creator_rules_source: Optional[str] = None
    default_creator_rule: CreatorRule = field(default_factory=CreatorRule)
    creator_rules: dict[str, CreatorRule] = field(default_factory=dict)


def _load_dotenv(path: Path) -> None:
    """轻量 .env 加载，不引入 python-dotenv 依赖。

    只为 os.environ 里不存在的 key 注入值。
    """
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.lower() in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _env_optional_int(name: str) -> Optional[int]:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return None
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def _env_csv(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return [part.strip() for part in raw.split(",") if part.strip()]


def _env_log_level(name: str, default: str = "INFO") -> str:
    raw = (os.environ.get(name) or default).strip().upper()
    allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
    if raw not in allowed:
        raise ValueError(
            t(None, "config.invalid_log_level", name=name, allowed=", ".join(sorted(allowed)))
        )
    return raw


def _env_lang(name: str, default: str = "zh-CN") -> str:
    raw = (os.environ.get(name) or default).strip()
    if not is_supported_lang(raw):
        raise ValueError(
            t(None, "config.invalid_lang", name=name, allowed=", ".join(SUPPORTED_LANGS))
        )
    return normalize_lang(raw)


def _parse_rule(data: dict) -> CreatorRule:
    return CreatorRule(
        skip=bool(data.get("skip", False)),
        fee_min=data.get("fee_min"),
        fee_max=data.get("fee_max"),
        tags_include=list(data.get("tags_include", []) or []),
        tags_exclude=list(data.get("tags_exclude", []) or []),
    )


def load_creator_rules(source: Optional[str]) -> tuple[CreatorRule, dict[str, CreatorRule]]:
    """source 可以是 .yaml/.yml 文件路径，也可以是 JSON 字符串。

    返回 (default_rule, dict[creator_id, CreatorRule])。
    """
    if not source:
        return CreatorRule(), {}

    raw: Optional[dict] = None
    candidate = Path(source)
    if candidate.suffix.lower() in (".yaml", ".yml") and candidate.is_file():
        raw = yaml.safe_load(candidate.read_text(encoding="utf-8"))
    else:
        try:
            raw = json.loads(source)
        except json.JSONDecodeError:
            return CreatorRule(), {}

    if not isinstance(raw, dict):
        return CreatorRule(), {}

    default_rule = _parse_rule(raw.get("defaults") or {})
    creators_raw = raw.get("creators") or {}
    creator_rules: dict[str, CreatorRule] = {}
    for cid, data in creators_raw.items():
        if isinstance(data, dict):
            creator_rules[str(cid)] = _parse_rule(data)
    return default_rule, creator_rules


def load_settings(project_root: Optional[Path] = None) -> Settings:
    """从 env / .env 加载 Settings。"""
    root = project_root or Path(__file__).resolve().parent
    _load_dotenv(root / ".env")

    session = os.environ.get("FANBOX_SESSION", "").strip()
    if not session:
        raise RuntimeError(t(_env_lang("FANBOX_LANG"), "config.session_missing"))

    user_agent = os.environ.get("FANBOX_USER_AGENT", "").strip() or (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    download_dir = Path(
        os.environ.get("FANBOX_DOWNLOAD_DIR") or (root / "data" / "downloads")
    )
    db_path = Path(
        os.environ.get("FANBOX_DB_PATH") or (root / "data" / "fanbox.db")
    )

    ext_whitelist = {e.lower() for e in _env_csv("FANBOX_EXT_WHITELIST", DEFAULT_EXT_WHITELIST)}

    creator_rules_source = os.environ.get("FANBOX_CREATOR_RULES")
    if creator_rules_source:
        candidate = Path(creator_rules_source)
        if candidate.suffix.lower() in (".yaml", ".yml") and not candidate.is_absolute():
            creator_rules_source = str((root / candidate).resolve())
    default_rule, creator_rules = load_creator_rules(creator_rules_source)

    concurrency = max(1, _env_int("FANBOX_CONCURRENCY", 3))
    interval_sec = max(0.0, _env_float("FANBOX_INTERVAL_SEC", 3.0))
    notify_min_new = max(0, _env_int("FANBOX_NOTIFY_MIN_NEW", 1))
    first_run_max_posts = max(0, _env_int("FANBOX_FIRST_RUN_MAX_POSTS", 50))
    post_403_retries = max(0, _env_int("FANBOX_POST_403_RETRIES", 3))
    post_403_backoff_base = max(
        0.0, _env_float("FANBOX_POST_403_BACKOFF_BASE", 30.0)
    )
    forbidden_fee_infer_threshold = max(
        0, _env_int("FANBOX_FORBIDDEN_FEE_INFER_THRESHOLD", 2)
    )
    run_lock_ttl_sec = max(60, _env_int("FANBOX_RUN_LOCK_TTL_SEC", 21600))

    return Settings(
        session=session,
        user_agent=user_agent,
        proxy=os.environ.get("FANBOX_PROXY") or None,
        download_dir=download_dir,
        db_path=db_path,
        log_level=_env_log_level("FANBOX_LOG_LEVEL"),
        mode_supporting=_env_bool("FANBOX_MODE_SUPPORTING", True),
        mode_following=_env_bool("FANBOX_MODE_FOLLOWING", False),
        interval_sec=interval_sec,
        concurrency=concurrency,
        ext_whitelist=ext_whitelist,
        fee_min=_env_int("FANBOX_FEE_MIN", 0),
        fee_max=_env_optional_int("FANBOX_FEE_MAX"),
        date_after=os.environ.get("FANBOX_DATE_AFTER") or None,
        name_rule=os.environ.get("FANBOX_NAME_RULE") or "{user}/{date}-{title}/{index}",
        notify_min_new=notify_min_new,
        first_run_max_posts=first_run_max_posts,
        post_403_retries=post_403_retries,
        post_403_backoff_base=post_403_backoff_base,
        forbidden_fee_infer_threshold=forbidden_fee_infer_threshold,
        run_lock_ttl_sec=run_lock_ttl_sec,
        bark_server=(os.environ.get("FANBOX_BARK_SERVER") or "https://api.day.app").rstrip("/"),
        bark_device_key=(os.environ.get("FANBOX_BARK_DEVICE_KEY") or "").strip(),
        bark_group=(os.environ.get("FANBOX_BARK_GROUP") or "FanboxMonitor").strip(),
        bark_sound=(os.environ.get("FANBOX_BARK_SOUND") or "").strip(),
        lang=_env_lang("FANBOX_LANG"),
        creator_rules_source=creator_rules_source,
        default_creator_rule=default_rule,
        creator_rules=creator_rules,
    )


def get_rule_for(settings: Settings, creator_id: str) -> CreatorRule:
    """返回该 creator 适用的合并规则（per-creator 字段优先于 default）。"""
    specific = settings.creator_rules.get(creator_id)
    if specific is None:
        return settings.default_creator_rule
    base = settings.default_creator_rule
    return CreatorRule(
        skip=specific.skip,
        fee_min=specific.fee_min if specific.fee_min is not None else base.fee_min,
        fee_max=specific.fee_max if specific.fee_max is not None else base.fee_max,
        tags_include=specific.tags_include or base.tags_include,
        tags_exclude=specific.tags_exclude or base.tags_exclude,
    )


def filter_revision(settings: Settings) -> str:
    """Return a stable key for rules that decide whether a post is skipped.

    Cursors and skipped rows are scoped by this value. If the user changes
    global filters, extension filters, or per-creator rules, the old cursor is
    ignored and previously skipped posts are evaluated again.
    """
    payload = {
        "fee_min": settings.fee_min,
        "fee_max": settings.fee_max,
        "date_after": settings.date_after,
        "ext_whitelist": sorted(settings.ext_whitelist),
        "default_rule": {
            "skip": settings.default_creator_rule.skip,
            "fee_min": settings.default_creator_rule.fee_min,
            "fee_max": settings.default_creator_rule.fee_max,
            "tags_include": settings.default_creator_rule.tags_include,
            "tags_exclude": settings.default_creator_rule.tags_exclude,
        },
        "creator_rules": {
            creator_id: {
                "skip": rule.skip,
                "fee_min": rule.fee_min,
                "fee_max": rule.fee_max,
                "tags_include": rule.tags_include,
                "tags_exclude": rule.tags_exclude,
            }
            for creator_id, rule in sorted(settings.creator_rules.items())
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
