"""SQLite 持久层：术语库、翻译记忆、会话记录。"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import paths
from .base_terms import BASE_BANK_DESCRIPTION, BASE_BANK_NAME, BASE_TERMS
from .models import SegmentRecord, Session, TMCandidate, TMEntry, Term, TermBank

log = logging.getLogger(__name__)

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS banks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    enabled     INTEGER NOT NULL DEFAULT 1,
    builtin     INTEGER NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS terms (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    bank_id        INTEGER NOT NULL REFERENCES banks(id) ON DELETE CASCADE,
    src            TEXT NOT NULL,
    dst            TEXT NOT NULL,
    aliases        TEXT NOT NULL DEFAULT '',
    note           TEXT NOT NULL DEFAULT '',
    domain         TEXT NOT NULL DEFAULT '',
    case_sensitive INTEGER NOT NULL DEFAULT 0,
    whole_word     INTEGER NOT NULL DEFAULT 1,
    enabled        INTEGER NOT NULL DEFAULT 1,
    priority       INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_terms_bank_src ON terms(bank_id, src);
CREATE INDEX IF NOT EXISTS idx_terms_bank ON terms(bank_id);

CREATE TABLE IF NOT EXISTS tm (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    src        TEXT NOT NULL,
    src_key    TEXT NOT NULL,
    dst        TEXT NOT NULL,
    src_lang   TEXT NOT NULL DEFAULT '',
    tgt_lang   TEXT NOT NULL DEFAULT '',
    quality    REAL NOT NULL DEFAULT 1.0,
    hits       INTEGER NOT NULL DEFAULT 0,
    origin     TEXT NOT NULL DEFAULT 'legacy',
    occurrences INTEGER NOT NULL DEFAULT 1,
    last_used_at TEXT NOT NULL DEFAULT '',
    last_seen_at TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tm_key ON tm(src_key, tgt_lang);
CREATE INDEX IF NOT EXISTS idx_tm_lang ON tm(tgt_lang);
CREATE INDEX IF NOT EXISTS idx_tm_quality ON tm(tgt_lang, quality);

CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    title         TEXT NOT NULL DEFAULT '',
    source_lang   TEXT NOT NULL DEFAULT 'auto',
    target_lang   TEXT NOT NULL DEFAULT 'zh',
    audio_source  TEXT NOT NULL DEFAULT '',
    asr_model     TEXT NOT NULL DEFAULT '',
    segment_count INTEGER NOT NULL DEFAULT 0,
    duration_s    REAL NOT NULL DEFAULT 0,
    avg_latency_ms REAL NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS segments (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq        INTEGER NOT NULL,
    t_start    REAL NOT NULL DEFAULT 0,
    t_end      REAL NOT NULL DEFAULT 0,
    src        TEXT NOT NULL DEFAULT '',
    dst        TEXT NOT NULL DEFAULT '',
    asr_ms     REAL NOT NULL DEFAULT 0,
    ttfb_ms    REAL NOT NULL DEFAULT 0,
    total_ms   REAL NOT NULL DEFAULT 0,
    terms      TEXT NOT NULL DEFAULT '',
    via_tm     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_session ON segments(session_id, seq);
"""

TM_V2_SCHEMA = """
CREATE TABLE IF NOT EXISTS tm_candidates (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    src                 TEXT NOT NULL,
    src_key             TEXT NOT NULL,
    dst                 TEXT NOT NULL,
    src_lang            TEXT NOT NULL DEFAULT '',
    tgt_lang            TEXT NOT NULL DEFAULT '',
    quality             REAL NOT NULL DEFAULT 1.0,
    occurrences         INTEGER NOT NULL DEFAULT 1,
    asr_confidence      REAL,
    asr_avg_logprob     REAL,
    asr_no_speech_prob  REAL,
    duration_s          REAL NOT NULL DEFAULT 0,
    chars               INTEGER NOT NULL DEFAULT 0,
    mt_model            TEXT NOT NULL DEFAULT '',
    asr_model           TEXT NOT NULL DEFAULT '',
    terms_json          TEXT NOT NULL DEFAULT '[]',
    flags_json          TEXT NOT NULL DEFAULT '[]',
    session_id          TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    first_seen_at       TEXT NOT NULL,
    last_seen_at        TEXT NOT NULL,
    reviewed_at         TEXT NOT NULL DEFAULT '',
    ai_state            TEXT NOT NULL DEFAULT 'none',
    ai_decision         TEXT NOT NULL DEFAULT '',
    ai_score            REAL,
    ai_issues_json      TEXT NOT NULL DEFAULT '[]',
    ai_suggested_dst    TEXT NOT NULL DEFAULT '',
    ai_reason           TEXT NOT NULL DEFAULT '',
    ai_model            TEXT NOT NULL DEFAULT '',
    ai_prompt_version   TEXT NOT NULL DEFAULT '',
    ai_reviewed_at      TEXT NOT NULL DEFAULT '',
    ai_latency_ms       INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_key ON tm_candidates(src_key, tgt_lang);
CREATE INDEX IF NOT EXISTS idx_candidates_status ON tm_candidates(status, last_seen_at);
CREATE INDEX IF NOT EXISTS idx_candidates_session ON tm_candidates(session_id);
CREATE INDEX IF NOT EXISTS idx_candidates_quality ON tm_candidates(status, quality);
"""

SCHEMA = SCHEMA + "\n" + TM_V2_SCHEMA

_SEED_BANK = "默认术语库"
_SEED_TERMS = [
    ("latency", "延迟", "技术", ""),
    ("VAD", "语音活动检测", "技术", "Voice Activity Detection"),
    ("ASR", "语音识别", "技术", "Automatic Speech Recognition"),
    ("LLM", "大语言模型", "技术", "Large Language Model"),
    ("prompt", "提示词", "技术", ""),
    ("streaming", "流式", "技术", ""),
]


def normalize_tm_key(text: str) -> str:
    import re

    value = text.strip().lower()
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" \t\r\n.,!?;:，。！？；：、…\"'“”‘’")
    return value


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else paths.db_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(
            str(self.path), check_same_thread=False, timeout=10.0
        )
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self._migrate()

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            self.conn.executescript(SCHEMA)
            self.conn.commit()
            self._migrate_v2()
            self._seed()
        else:
            # 老库可能缺少后来新增的表；先幂等补齐，再逐版本升级。
            if version < SCHEMA_VERSION:
                self.conn.executescript(SCHEMA)
                self.conn.commit()
            if version < 2:
                self._migrate_v2()
        if version < SCHEMA_VERSION:
            self._migrate_v3()
        else:
            # 内置库是只读的，但内容会随版本更新；每次启动同步一次。
            self._ensure_base_bank()

    def _migrate_v2(self) -> None:
        """v1 -> v2：审核状态、学习来源、候选表。"""
        columns = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(tm)").fetchall()
        }
        additions = {
            "origin": "TEXT NOT NULL DEFAULT 'legacy'",
            "occurrences": "INTEGER NOT NULL DEFAULT 1",
            "last_used_at": "TEXT NOT NULL DEFAULT ''",
            "last_seen_at": "TEXT NOT NULL DEFAULT ''",
            "reviewed_at": "TEXT NOT NULL DEFAULT ''",
        }
        for name, definition in additions.items():
            if name not in columns:
                self.conn.execute(f"ALTER TABLE tm ADD COLUMN {name} {definition}")
        self.conn.executescript(TM_V2_SCHEMA)
        self.conn.execute("PRAGMA user_version=2")
        self.conn.commit()
        log.info("数据库已升级到 v2（候选审核）")

    def _migrate_v3(self) -> None:
        """v2 -> v3：内置只读基础术语库。"""
        columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(banks)").fetchall()
        }
        if "builtin" not in columns:
            self.conn.execute(
                "ALTER TABLE banks ADD COLUMN builtin INTEGER NOT NULL DEFAULT 0"
            )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_banks_builtin ON banks(builtin, sort_order)"
        )
        self.conn.execute("PRAGMA user_version=3")
        self.conn.commit()
        self._ensure_base_bank()
        log.info("数据库已升级到 v3（内置基础术语库）")

    def _ensure_base_bank(self) -> None:
        """确保内置基础库存在，并补齐缺失的内置术语。

        已停用的基础库/单条术语会被保留，不会因为重启被重新启用。
        """
        ts = now_iso()
        with self._lock, self.conn:
            row = self.conn.execute(
                "SELECT id, builtin FROM banks WHERE name=?", (BASE_BANK_NAME,)
            ).fetchone()
            if row is None:
                cur = self.conn.execute(
                    "INSERT INTO banks(name, description, enabled, builtin, sort_order,"
                    " created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                    (BASE_BANK_NAME, BASE_BANK_DESCRIPTION, 1, 1, 99, ts, ts),
                )
                bank_id = int(cur.lastrowid)
            else:
                bank_id = int(row["id"])
                if not row["builtin"]:
                    # 用户恰好用了同名库：不改写用户数据，避免误伤。
                    log.warning("存在同名用户术语库，跳过内置基础库初始化：%s", BASE_BANK_NAME)
                    return
            existing = {
                r["src"]: r["id"]
                for r in self.conn.execute(
                    "SELECT id, src FROM terms WHERE bank_id=?", (bank_id,)
                ).fetchall()
            }
            for src, dst, domain, aliases in BASE_TERMS:
                term_id = existing.get(src)
                if term_id is None:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO terms(bank_id, src, dst, aliases, note, domain,"
                        " case_sensitive, whole_word, enabled, priority, created_at, updated_at)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (bank_id, src, dst, aliases, "内置基础术语", domain, 0, 1, 1, 0, ts, ts),
                    )
                    continue
                # 内置术语只读，但内容由程序维护；保留用户的启用/停用选择。
                self.conn.execute(
                    "UPDATE terms SET dst=?, aliases=?, note=?, domain=?,"
                    " case_sensitive=0, whole_word=1, priority=0, updated_at=?"
                    " WHERE id=?",
                    (dst, aliases, "内置基础术语", domain, ts, term_id),
                )
            if not row:
                log.info("已创建内置基础术语库（%d 条）", len(BASE_TERMS))

    def _is_builtin_bank(self, bank_id: int) -> bool:
        row = self.conn.execute(
            "SELECT builtin FROM banks WHERE id=?", (bank_id,)
        ).fetchone()
        return bool(row and row["builtin"])

    def _seed(self) -> None:
        if self.conn.execute("SELECT COUNT(*) FROM banks").fetchone()[0]:
            return
        ts = now_iso()
        cur = self.conn.execute(
            "INSERT INTO banks(name, description, enabled, sort_order, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (_SEED_BANK, "首次启动自带的示例术语，可自由修改或删除", 1, 0, ts, ts),
        )
        bank_id = int(cur.lastrowid)
        for src, dst, domain, aliases in _SEED_TERMS:
            self.conn.execute(
                "INSERT INTO terms(bank_id, src, dst, aliases, note, domain,"
                " case_sensitive, whole_word, enabled, priority, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (bank_id, src, dst, aliases, "", domain, 0, 1, 1, 0, ts, ts),
            )
        self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # ------------------------------------------------------------------ 术语库
    def list_banks(self) -> list[TermBank]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT b.*, COUNT(t.id) AS term_count FROM banks b"
                " LEFT JOIN terms t ON t.bank_id=b.id"
                " GROUP BY b.id ORDER BY b.builtin DESC, b.sort_order, b.id"
            ).fetchall()
        return [TermBank.from_row(r) for r in rows]

    def get_bank(self, bank_id: int) -> TermBank | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT b.*, (SELECT COUNT(*) FROM terms WHERE bank_id=b.id) AS term_count"
                " FROM banks b WHERE b.id=?",
                (bank_id,),
            ).fetchone()
        return TermBank.from_row(row) if row else None

    def ensure_default_bank(self) -> TermBank:
        banks = self.list_banks()
        if banks:
            return banks[0]
        bank_id = self.create_bank(_SEED_BANK, "默认术语库")
        bank = self.get_bank(bank_id)
        assert bank is not None
        return bank

    def create_bank(self, name: str, description: str = "") -> int:
        name = name.strip()
        if not name:
            raise ValueError("术语库名称不能为空")
        ts = now_iso()
        with self._lock, self.conn:
            order = self.conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM banks"
            ).fetchone()[0]
            try:
                cur = self.conn.execute(
                    "INSERT INTO banks(name, description, enabled, sort_order, created_at, updated_at)"
                    " VALUES(?,?,?,?,?,?)",
                    (name, description.strip(), 1, order, ts, ts),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"术语库“{name}”已存在") from exc
            return int(cur.lastrowid)

    def update_bank(
        self, bank_id: int, name: str | None = None, description: str | None = None
    ) -> None:
        if name is not None or description is not None:
            with self._lock:
                if self._is_builtin_bank(bank_id):
                    raise ValueError("内置基础术语库为只读，不能重命名或修改说明")
        fields: list[str] = []
        values: list[Any] = []
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("术语库名称不能为空")
            fields.append("name=?")
            values.append(name)
        if description is not None:
            fields.append("description=?")
            values.append(description.strip())
        if not fields:
            return
        fields.append("updated_at=?")
        values.append(now_iso())
        values.append(bank_id)
        with self._lock, self.conn:
            try:
                self.conn.execute(
                    f"UPDATE banks SET {', '.join(fields)} WHERE id=?", values
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("术语库名称重复") from exc

    def set_bank_enabled(self, bank_id: int, enabled: bool) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE banks SET enabled=?, updated_at=? WHERE id=?",
                (1 if enabled else 0, now_iso(), bank_id),
            )

    def delete_bank(self, bank_id: int) -> None:
        with self._lock:
            if self._is_builtin_bank(bank_id):
                raise ValueError("内置基础术语库不能删除，只能停用")
            with self.conn:
                self.conn.execute("DELETE FROM banks WHERE id=?", (bank_id,))

    # ------------------------------------------------------------------ 术语
    def list_terms(self, bank_id: int, query: str = "", limit: int = 5000) -> list[Term]:
        sql = (
            "SELECT t.*, b.name AS bank_name FROM terms t JOIN banks b ON b.id=t.bank_id"
            " WHERE t.bank_id=?"
        )
        params: list[Any] = [bank_id]
        query = query.strip()
        if query:
            escaped = query.replace("%", "\\%").replace("_", "\\_")
            like = f"%{escaped}%"
            sql += " AND (t.src LIKE ? ESCAPE '\\' OR t.dst LIKE ? ESCAPE '\\' OR t.aliases LIKE ? ESCAPE '\\' OR t.note LIKE ? ESCAPE '\\')"
            params.extend([like, like, like, like])
        sql += " ORDER BY t.enabled DESC, t.priority DESC, t.id LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [Term.from_row(r) for r in rows]

    def active_terms(self) -> list[Term]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT t.*, b.name AS bank_name, b.sort_order AS bank_sort"
                " FROM terms t JOIN banks b ON b.id=t.bank_id"
                " WHERE t.enabled=1 AND b.enabled=1"
                " ORDER BY t.priority DESC, b.sort_order, t.id"
            ).fetchall()
        terms = [Term.from_row(r) for r in rows]
        return terms

    def get_term(self, term_id: int) -> Term | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT t.*, b.name AS bank_name FROM terms t JOIN banks b ON b.id=t.bank_id"
                " WHERE t.id=?",
                (term_id,),
            ).fetchone()
        return Term.from_row(row) if row else None

    def add_term(
        self,
        bank_id: int,
        src: str,
        dst: str,
        aliases: str = "",
        note: str = "",
        domain: str = "",
        case_sensitive: bool = False,
        whole_word: bool = True,
        enabled: bool = True,
        priority: int = 0,
    ) -> int:
        src = src.strip()
        dst = dst.strip()
        if not src or not dst:
            raise ValueError("原文和译文不能为空")
        ts = now_iso()
        with self._lock, self.conn:
            if self._is_builtin_bank(bank_id):
                raise ValueError("内置基础术语库为只读，不能新增术语")
            try:
                cur = self.conn.execute(
                    "INSERT INTO terms(bank_id, src, dst, aliases, note, domain,"
                    " case_sensitive, whole_word, enabled, priority, created_at, updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        bank_id,
                        src,
                        dst,
                        aliases.strip(),
                        note.strip(),
                        domain.strip(),
                        1 if case_sensitive else 0,
                        1 if whole_word else 0,
                        1 if enabled else 0,
                        int(priority),
                        ts,
                        ts,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"该术语库中已存在原文“{src}”") from exc
            return int(cur.lastrowid)

    def update_term(self, term_id: int, **fields: Any) -> None:
        allowed = {
            "src",
            "dst",
            "aliases",
            "note",
            "domain",
            "case_sensitive",
            "whole_word",
            "enabled",
            "priority",
            "bank_id",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        if any(key != "enabled" for key in updates):
            with self._lock:
                row = self.conn.execute(
                    "SELECT b.builtin FROM terms t JOIN banks b ON b.id=t.bank_id"
                    " WHERE t.id=?",
                    (term_id,),
                ).fetchone()
                if row and row["builtin"]:
                    raise ValueError("内置基础术语库为只读，只能启用/停用单条术语")
        for key in ("case_sensitive", "whole_word", "enabled"):
            if key in updates:
                updates[key] = 1 if updates[key] else 0
        if "src" in updates:
            updates["src"] = str(updates["src"]).strip()
        if "dst" in updates:
            updates["dst"] = str(updates["dst"]).strip()
        updates["updated_at"] = now_iso()
        sets = ", ".join(f"{k}=?" for k in updates)
        with self._lock, self.conn:
            try:
                self.conn.execute(
                    f"UPDATE terms SET {sets} WHERE id=?",
                    [*updates.values(), term_id],
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("同一术语库中原文重复") from exc

    def delete_terms(self, term_ids: Iterable[int]) -> int:
        ids = [int(i) for i in term_ids]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        with self._lock, self.conn:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM terms t JOIN banks b ON b.id=t.bank_id"
                f" WHERE t.id IN ({placeholders}) AND b.builtin=1",
                ids,
            ).fetchone()
            if row and row["n"]:
                raise ValueError("内置基础术语库为只读，不能删除其中的术语")
            cur = self.conn.execute(
                f"DELETE FROM terms WHERE id IN ({placeholders})", ids
            )
            return cur.rowcount

    def import_terms(self, bank_id: int, rows: Sequence[dict[str, Any]]) -> tuple[int, int]:
        """按原文合并导入，返回 (新增, 更新)。"""
        added = updated = 0
        ts = now_iso()
        with self._lock, self.conn:
            if self._is_builtin_bank(bank_id):
                raise ValueError("内置基础术语库为只读，不能导入术语")
            for row in rows:
                src = str(row.get("src", "")).strip()
                dst = str(row.get("dst", "")).strip()
                if not src or not dst:
                    continue
                aliases = str(row.get("aliases", "") or "").strip()
                note = str(row.get("note", "") or "").strip()
                domain = str(row.get("domain", "") or "").strip()
                existing = self.conn.execute(
                    "SELECT id FROM terms WHERE bank_id=? AND src=?", (bank_id, src)
                ).fetchone()
                if existing:
                    self.conn.execute(
                        "UPDATE terms SET dst=?, aliases=?, note=?, domain=?, updated_at=?"
                        " WHERE id=?",
                        (dst, aliases, note, domain, ts, existing["id"]),
                    )
                    updated += 1
                else:
                    self.conn.execute(
                        "INSERT INTO terms(bank_id, src, dst, aliases, note, domain,"
                        " case_sensitive, whole_word, enabled, priority, created_at, updated_at)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (bank_id, src, dst, aliases, note, domain, 0, 1, 1, 0, ts, ts),
                    )
                    added += 1
        return added, updated

    # ------------------------------------------------------------------ 翻译记忆
    def list_tm(
        self, tgt_lang: str | None = None, query: str = "", limit: int = 2000
    ) -> list[TMEntry]:
        sql = "SELECT * FROM tm WHERE 1=1"
        params: list[Any] = []
        if tgt_lang:
            sql += " AND tgt_lang=?"
            params.append(tgt_lang)
        if query.strip():
            like = f"%{query.strip()}%"
            sql += " AND (src LIKE ? OR dst LIKE ?)"
            params.extend([like, like])
        sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [TMEntry.from_row(r) for r in rows]

    def tm_count(self, tgt_lang: str | None = None) -> int:
        with self._lock:
            if tgt_lang:
                return int(
                    self.conn.execute(
                        "SELECT COUNT(*) FROM tm WHERE tgt_lang=?", (tgt_lang,)
                    ).fetchone()[0]
                )
            return int(self.conn.execute("SELECT COUNT(*) FROM tm").fetchone()[0])

    def upsert_tm(
        self,
        src: str,
        dst: str,
        src_lang: str = "",
        tgt_lang: str = "",
        quality: float = 1.0,
        origin: str = "human",
        occurrences: int = 1,
    ) -> None:
        src = src.strip()
        dst = dst.strip()
        if not src or not dst:
            return
        key = normalize_tm_key(src)
        if not key:
            return
        ts = now_iso()
        with self._lock, self.conn:
            row = self.conn.execute(
                "SELECT id, quality, origin FROM tm WHERE src_key=? AND tgt_lang=?",
                (key, tgt_lang),
            ).fetchone()
            if row:
                old_quality = float(row["quality"] or 0)
                old_origin = str(row["origin"] or "legacy")
                # 人工条目永不被自动学习降级覆盖；人工审核可以修正任何条目。
                protected = old_origin == "human" and origin == "auto"
                if protected:
                    self.conn.execute(
                        "UPDATE tm SET last_seen_at=?, updated_at=? WHERE id=?",
                        (ts, ts, row["id"]),
                    )
                elif origin == "human" or float(quality) >= old_quality:
                    self.conn.execute(
                        "UPDATE tm SET dst=?, quality=?, origin=?,"
                        " occurrences=MAX(occurrences, ?), last_seen_at=?, updated_at=?"
                        " WHERE id=?",
                        (
                            dst,
                            float(quality),
                            origin,
                            int(occurrences),
                            ts,
                            ts,
                            row["id"],
                        ),
                    )
                else:
                    self.conn.execute(
                        "UPDATE tm SET last_seen_at=?, updated_at=? WHERE id=?",
                        (ts, ts, row["id"]),
                    )
            else:
                self.conn.execute(
                    "INSERT INTO tm(src, src_key, dst, src_lang, tgt_lang, quality, hits,"
                    " origin, occurrences, last_seen_at, created_at, updated_at)"
                    " VALUES(?,?,?,?,?,?,0,?,?,?,?,?)",
                    (
                        src,
                        key,
                        dst,
                        src_lang,
                        tgt_lang,
                        float(quality),
                        origin,
                        int(occurrences),
                        ts,
                        ts,
                        ts,
                    ),
                )

    def delete_tm(self, tm_ids: Iterable[int]) -> int:
        ids = [int(i) for i in tm_ids]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        with self._lock, self.conn:
            cur = self.conn.execute(f"DELETE FROM tm WHERE id IN ({placeholders})", ids)
            return cur.rowcount

    def clear_tm(self) -> int:
        with self._lock, self.conn:
            cur = self.conn.execute("DELETE FROM tm")
            return cur.rowcount

    def update_tm(self, tm_id: int, src: str, dst: str) -> None:
        src = src.strip()
        dst = dst.strip()
        if not src or not dst:
            raise ValueError("原文和译文不能为空")
        key = normalize_tm_key(src)
        with self._lock, self.conn:
            row = self.conn.execute("SELECT tgt_lang FROM tm WHERE id=?", (tm_id,)).fetchone()
            if not row:
                return
            try:
                self.conn.execute(
                    "UPDATE tm SET src=?, src_key=?, dst=?, updated_at=? WHERE id=?",
                    (src, key, dst, now_iso(), tm_id),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("语料库中已存在相同原文") from exc

    def bump_tm(self, tm_id: int) -> None:
        ts = now_iso()
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE tm SET hits=hits+1, last_used_at=?, updated_at=? WHERE id=?",
                (ts, ts, tm_id),
            )

    # -------------------------------------------------------------- 候选审核
    def candidate_count(
        self,
        status: str | None = "pending",
        session_id: str | None = None,
        tgt_lang: str | None = None,
    ) -> int:
        sql = "SELECT COUNT(*) FROM tm_candidates WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status=?"
            params.append(status)
        if session_id:
            sql += " AND session_id=?"
            params.append(session_id)
        if tgt_lang:
            sql += " AND tgt_lang=?"
            params.append(tgt_lang)
        with self._lock:
            return int(self.conn.execute(sql, params).fetchone()[0])

    def list_candidates(
        self,
        status: str | None = "pending",
        session_id: str | None = None,
        query: str = "",
        limit: int = 500,
    ) -> list[TMCandidate]:
        sql = "SELECT * FROM tm_candidates WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status=?"
            params.append(status)
        if session_id:
            sql += " AND session_id=?"
            params.append(session_id)
        if query.strip():
            like = f"%{query.strip()}%"
            sql += " AND (src LIKE ? OR dst LIKE ?)"
            params.extend([like, like])
        sql += " ORDER BY last_seen_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [TMCandidate.from_row(r) for r in rows]

    def get_candidate(self, candidate_id: int) -> TMCandidate | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM tm_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
        return TMCandidate.from_row(row) if row else None

    def upsert_candidate(
        self,
        *,
        src: str,
        dst: str,
        src_lang: str = "",
        tgt_lang: str = "zh",
        quality: float = 1.0,
        occurrences: int = 1,
        session_id: str | None = None,
        duration_s: float = 0.0,
        chars: int = 0,
        mt_model: str = "",
        asr_model: str = "",
        terms: list[dict[str, str]] | None = None,
        flags: list[str] | None = None,
        asr_confidence: float | None = None,
        asr_avg_logprob: float | None = None,
        asr_no_speech_prob: float | None = None,
    ) -> int | None:
        """同一原文只保留一条候选；已审核条目不会再次进入候选。"""
        src = src.strip()
        dst = dst.strip()
        if not src or not dst:
            return None
        key = normalize_tm_key(src)
        if not key:
            return None
        ts = now_iso()
        terms_json = json.dumps(terms or [], ensure_ascii=False)
        flags_json = json.dumps(flags or [], ensure_ascii=False)
        with self._lock, self.conn:
            approved = self.conn.execute(
                "SELECT 1 FROM tm WHERE src_key=? AND tgt_lang=?", (key, tgt_lang)
            ).fetchone()
            if approved:
                return None
            row = self.conn.execute(
                "SELECT id, quality, dst, status, occurrences FROM tm_candidates"
                " WHERE src_key=? AND tgt_lang=?",
                (key, tgt_lang),
            ).fetchone()
            if row:
                if str(row["status"]) == "rejected":
                    self.conn.execute(
                        "UPDATE tm_candidates SET occurrences=occurrences+1, last_seen_at=?"
                        " WHERE id=?",
                        (ts, row["id"]),
                    )
                    return int(row["id"])
                old_quality = float(row["quality"] or 0)
                self.conn.execute(
                    "UPDATE tm_candidates SET occurrences=occurrences+1, quality=?,"
                    " dst=CASE WHEN ? >= quality THEN ? ELSE dst END,"
                    " duration_s=?, chars=?, mt_model=?, asr_model=?,"
                    " terms_json=?, flags_json=?, last_seen_at=?,"
                    " asr_confidence=COALESCE(?, asr_confidence),"
                    " asr_avg_logprob=COALESCE(?, asr_avg_logprob),"
                    " asr_no_speech_prob=COALESCE(?, asr_no_speech_prob)"
                    " WHERE id=?",
                    (
                        max(old_quality, float(quality)),
                        float(quality),
                        dst,
                        float(duration_s),
                        int(chars),
                        mt_model,
                        asr_model,
                        terms_json,
                        flags_json,
                        ts,
                        asr_confidence,
                        asr_avg_logprob,
                        asr_no_speech_prob,
                        row["id"],
                    ),
                )
                return int(row["id"])
            try:
                cur = self.conn.execute(
                    "INSERT INTO tm_candidates(src, src_key, dst, src_lang, tgt_lang,"
                    " quality, occurrences, asr_confidence, asr_avg_logprob,"
                    " asr_no_speech_prob, duration_s, chars, mt_model, asr_model,"
                    " terms_json, flags_json, session_id, status, first_seen_at,"
                    " last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'pending',?,?)",
                    (
                        src,
                        key,
                        dst,
                        src_lang,
                        tgt_lang,
                        float(quality),
                        int(occurrences),
                        asr_confidence,
                        asr_avg_logprob,
                        asr_no_speech_prob,
                        float(duration_s),
                        int(chars),
                        mt_model,
                        asr_model,
                        terms_json,
                        flags_json,
                        session_id,
                        ts,
                        ts,
                    ),
                )
            except sqlite3.IntegrityError:
                return None
            return int(cur.lastrowid)

    def update_candidate(
        self,
        candidate_id: int,
        src: str | None = None,
        dst: str | None = None,
        quality: float | None = None,
        flags: list[str] | None = None,
    ) -> None:
        candidate = self.get_candidate(candidate_id)
        if not candidate:
            return
        updates: dict[str, Any] = {}
        if src is not None:
            src = src.strip()
            if not src:
                raise ValueError("原文不能为空")
            updates["src"] = src
            updates["src_key"] = normalize_tm_key(src)
        if dst is not None:
            dst = dst.strip()
            if not dst:
                raise ValueError("译文不能为空")
            updates["dst"] = dst
        if quality is not None:
            updates["quality"] = max(0.0, min(1.0, float(quality)))
        if flags is not None:
            updates["flags_json"] = json.dumps(flags, ensure_ascii=False)
        if not updates:
            return
        sets = ", ".join(f"{key}=?" for key in updates)
        with self._lock, self.conn:
            try:
                self.conn.execute(
                    f"UPDATE tm_candidates SET {sets}, last_seen_at=? WHERE id=?",
                    [*updates.values(), now_iso(), candidate_id],
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("已有相同原文的候选") from exc

    def approve_candidate(
        self,
        candidate_id: int,
        src: str | None = None,
        dst: str | None = None,
        origin: str = "human",
        quality: float | None = None,
    ) -> bool:
        candidate = self.get_candidate(candidate_id)
        if not candidate:
            return False
        final_src = (src if src is not None else candidate.src).strip()
        final_dst = (dst if dst is not None else candidate.dst).strip()
        if not final_src or not final_dst:
            raise ValueError("原文和译文不能为空")
        final_quality = (
            float(quality)
            if quality is not None
            else (1.0 if origin == "human" else max(0.5, candidate.quality))
        )
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM tm_candidates WHERE id=?", (candidate_id,))
        self.upsert_tm(
            final_src,
            final_dst,
            src_lang=candidate.src_lang,
            tgt_lang=candidate.tgt_lang,
            quality=final_quality,
            origin=origin,
            occurrences=candidate.occurrences,
        )
        return True

    def reject_candidate(self, candidate_id: int, reason: str = "") -> None:
        candidate = self.get_candidate(candidate_id)
        if not candidate:
            return
        flags = list(candidate.flags)
        if reason and reason not in flags:
            flags.append(reason)
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE tm_candidates SET status='rejected', flags_json=?,"
                " reviewed_at=?, ai_state='done', ai_decision='reject' WHERE id=?",
                (json.dumps(flags, ensure_ascii=False), now_iso(), candidate_id),
            )

    def restore_candidate(self, candidate_id: int) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE tm_candidates SET status='pending', reviewed_at='' WHERE id=?",
                (candidate_id,),
            )

    def delete_candidates(self, candidate_ids: Iterable[int]) -> int:
        ids = [int(i) for i in candidate_ids]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        with self._lock, self.conn:
            cur = self.conn.execute(
                f"DELETE FROM tm_candidates WHERE id IN ({placeholders})", ids
            )
            return cur.rowcount

    def clear_candidates(self, status: str = "rejected") -> int:
        with self._lock, self.conn:
            cur = self.conn.execute(
                "DELETE FROM tm_candidates WHERE status=?", (status,)
            )
            return cur.rowcount

    def set_candidate_ai_state(self, candidate_ids: Iterable[int], state: str) -> None:
        ids = [int(i) for i in candidate_ids]
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        with self._lock, self.conn:
            self.conn.execute(
                f"UPDATE tm_candidates SET ai_state=? WHERE id IN ({placeholders})",
                [state, *ids],
            )

    def save_ai_review(
        self,
        candidate_id: int,
        decision: str,
        score: float,
        issues: list[str],
        suggested_dst: str,
        reason: str,
        model: str,
        prompt_version: str,
        latency_ms: int,
    ) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE tm_candidates SET ai_state='done', ai_decision=?, ai_score=?,"
                " ai_issues_json=?, ai_suggested_dst=?, ai_reason=?, ai_model=?,"
                " ai_prompt_version=?, ai_reviewed_at=?, ai_latency_ms=? WHERE id=?",
                (
                    decision,
                    max(0.0, min(1.0, float(score))),
                    json.dumps(issues, ensure_ascii=False),
                    suggested_dst,
                    reason,
                    model,
                    prompt_version,
                    now_iso(),
                    int(latency_ms),
                    candidate_id,
                ),
            )

    def candidate_stats(self) -> dict[str, int]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT status, COUNT(*) AS n FROM tm_candidates GROUP BY status"
            ).fetchall()
            ai = self.conn.execute(
                "SELECT COUNT(*) AS n FROM tm_candidates WHERE status='pending'"
                " AND ai_decision='approve'"
            ).fetchone()[0]
        result = {"pending": 0, "rejected": 0}
        for row in rows:
            result[str(row["status"])] = int(row["n"])
        result["ai_approve"] = int(ai)
        return result

    # ------------------------------------------------------------------ 会话
    def create_session(
        self,
        session_id: str,
        title: str,
        source_lang: str,
        target_lang: str,
        audio_source: str,
        asr_model: str,
    ) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT INTO sessions(id, started_at, title, source_lang, target_lang,"
                " audio_source, asr_model, status) VALUES(?,?,?,?,?,?,?, 'running')",
                (
                    session_id,
                    now_iso(),
                    title,
                    source_lang,
                    target_lang,
                    audio_source,
                    asr_model,
                ),
            )

    def add_segment(
        self,
        session_id: str,
        segment_id: str,
        seq: int,
        t_start: float,
        t_end: float,
        src: str,
        asr_ms: float,
        terms: list[dict[str, str]],
    ) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO segments(id, session_id, seq, t_start, t_end, src,"
                " dst, asr_ms, ttfb_ms, total_ms, terms, via_tm, created_at)"
                " VALUES(?,?,?,?,?,?,'',?,0,0,?,0,?)",
                (
                    segment_id,
                    session_id,
                    seq,
                    round(t_start, 3),
                    round(t_end, 3),
                    src,
                    round(asr_ms, 1),
                    json.dumps(terms, ensure_ascii=False),
                    now_iso(),
                ),
            )

    def update_segment_translation(
        self,
        segment_id: str,
        dst: str,
        ttfb_ms: float,
        total_ms: float,
        via_tm: bool,
    ) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE segments SET dst=?, ttfb_ms=?, total_ms=?, via_tm=? WHERE id=?",
                (
                    dst,
                    round(ttfb_ms, 1),
                    round(total_ms, 1),
                    1 if via_tm else 0,
                    segment_id,
                ),
            )

    def finish_session(self, session_id: str, duration_s: float) -> None:
        with self._lock, self.conn:
            row = self.conn.execute(
                "SELECT AVG(total_ms) AS avg_ms, COUNT(*) AS cnt FROM segments"
                " WHERE session_id=? AND total_ms > 0",
                (session_id,),
            ).fetchone()
            avg_ms = float(row["avg_ms"] or 0.0)
            self.conn.execute(
                "UPDATE sessions SET ended_at=?, duration_s=?, segment_count=?,"
                " avg_latency_ms=?, status='done' WHERE id=?",
                (
                    now_iso(),
                    round(float(duration_s), 1),
                    int(row["cnt"] or 0),
                    round(avg_ms, 1),
                    session_id,
                ),
            )

    def mark_session_aborted(self, session_id: str) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE sessions SET status='aborted', ended_at=? WHERE id=?",
                (now_iso(), session_id),
            )

    def list_sessions(self, limit: int = 100) -> list[Session]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT s.*,"
                " (SELECT COUNT(*) FROM segments g WHERE g.session_id=s.id AND g.total_ms>0)"
                "   AS live_count,"
                " (SELECT COALESCE(AVG(g.total_ms),0) FROM segments g"
                "   WHERE g.session_id=s.id AND g.total_ms>0) AS live_avg"
                " FROM sessions s ORDER BY s.started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result: list[Session] = []
        for row in rows:
            session = Session.from_row(row)
            session.segment_count = int(row["live_count"] or 0)
            session.avg_latency_ms = float(row["live_avg"] or 0.0)
            result.append(session)
        return result

    def get_session(self, session_id: str) -> Session | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT s.*,"
                " (SELECT COUNT(*) FROM segments g WHERE g.session_id=s.id AND g.total_ms>0)"
                "   AS live_count,"
                " (SELECT COALESCE(AVG(g.total_ms),0) FROM segments g"
                "   WHERE g.session_id=s.id AND g.total_ms>0) AS live_avg"
                " FROM sessions s WHERE s.id=?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        session = Session.from_row(row)
        session.segment_count = int(row["live_count"] or 0)
        session.avg_latency_ms = float(row["live_avg"] or 0.0)
        return session

    def session_segments(self, session_id: str) -> list[SegmentRecord]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM segments WHERE session_id=? ORDER BY seq", (session_id,)
            ).fetchall()
        return [SegmentRecord.from_row(r) for r in rows]

    def delete_session(self, session_id: str) -> None:
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))

    def clear_sessions(self, keep_id: str | None = None) -> int:
        with self._lock, self.conn:
            if keep_id:
                cur = self.conn.execute("DELETE FROM sessions WHERE id != ?", (keep_id,))
            else:
                cur = self.conn.execute("DELETE FROM sessions")
            return cur.rowcount

    def session_exists(self, session_id: str) -> bool:
        if not session_id:
            return False
        with self._lock:
            row = self.conn.execute(
                "SELECT 1 FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
        return row is not None

    def overview(self) -> dict[str, Any]:
        with self._lock:
            banks = self.conn.execute("SELECT COUNT(*) FROM banks").fetchone()[0]
            terms = self.conn.execute("SELECT COUNT(*) FROM terms").fetchone()[0]
            enabled_terms = self.conn.execute(
                "SELECT COUNT(*) FROM terms t JOIN banks b ON b.id=t.bank_id"
                " WHERE t.enabled=1 AND b.enabled=1"
            ).fetchone()[0]
            tm = self.conn.execute("SELECT COUNT(*) FROM tm").fetchone()[0]
            sessions = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            segs = self.conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
        return {
            "banks": int(banks),
            "terms": int(terms),
            "enabled_terms": int(enabled_terms),
            "tm": int(tm),
            "sessions": int(sessions),
            "segments": int(segs),
        }
