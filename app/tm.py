"""翻译记忆（语料库）：整句精确命中 + 高相似度模糊命中，全部在内存中完成。"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from .db import Database, normalize_tm_key
from .models import TMEntry

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TMHit:
    entry: TMEntry
    score: float
    exact: bool

    @property
    def percent(self) -> int:
        return int(round(self.score * 100))


class TranslationMemory:
    def __init__(
        self,
        db: Database,
        tgt_lang: str,
        threshold: float = 0.93,
        max_entries: int = 50000,
        min_quality: float = 0.8,
    ) -> None:
        self.db = db
        self.tgt_lang = tgt_lang
        self.threshold = threshold
        self.max_entries = max_entries
        self.min_quality = min_quality
        self._lock = threading.RLock()
        self._exact: dict[str, TMEntry] = {}
        self._keys: list[str] = []
        self._by_key: dict[str, TMEntry] = {}
        self.reload()

    def reload(self) -> None:
        entries = self.db.list_tm(tgt_lang=self.tgt_lang, limit=self.max_entries)
        exact: dict[str, TMEntry] = {}
        by_key: dict[str, TMEntry] = {}
        for entry in entries:
            if float(entry.quality or 0) < self.min_quality:
                continue
            key = normalize_tm_key(entry.src)
            if not key:
                continue
            exact[key] = entry
            by_key[key] = entry
        with self._lock:
            self._exact = exact
            self._by_key = by_key
            self._keys = list(by_key.keys())
        log.debug("翻译记忆已加载：%s 条", len(self._keys))

    def __len__(self) -> int:
        with self._lock:
            return len(self._keys)

    def lookup(self, text: str) -> TMHit | None:
        key = normalize_tm_key(text)
        if not key:
            return None
        with self._lock:
            entry = self._exact.get(key)
            if entry is not None:
                return TMHit(entry, 1.0, True)
            if len(key) < 3 or not self._keys or len(self._keys) > 30000:
                return None
            keys = self._keys
            by_key = self._by_key
        result = process.extractOne(key, keys, scorer=fuzz.ratio, score_cutoff=self.threshold * 100)
        if not result:
            return None
        matched_key, score, _ = result
        entry = by_key.get(matched_key)
        if entry is None:
            return None
        # 模糊命中还必须长度接近，避免把短句套到长句上。
        shorter = max(1, min(len(key), len(matched_key)))
        longer = max(len(key), len(matched_key))
        if longer / shorter > 1.30:
            return None
        return TMHit(entry, float(score) / 100.0, False)

    def add(self, src: str, dst: str, src_lang: str = "", quality: float = 1.0) -> None:
        key = normalize_tm_key(src)
        if not key:
            return
        self.db.upsert_tm(src, dst, src_lang=src_lang, tgt_lang=self.tgt_lang, quality=quality)
        # 轻量地同步内存，避免每次重载整个表
        with self._lock:
            is_new = key not in self._by_key
            existing = self._by_key.get(key)
            entry = existing or TMEntry(
                id=0, src=src.strip(), dst=dst.strip(), src_lang=src_lang, tgt_lang=self.tgt_lang
            )
            entry = TMEntry(
                id=entry.id,
                src=src.strip(),
                dst=dst.strip(),
                src_lang=src_lang,
                tgt_lang=self.tgt_lang,
                quality=quality,
                hits=entry.hits,
                created_at=entry.created_at,
                updated_at=entry.updated_at,
            )
            self._by_key[key] = entry
            self._exact[key] = entry
            if is_new:
                self._keys.append(key)

    def bump(self, tm_id: int) -> None:
        if tm_id:
            self.db.bump_tm(tm_id)
