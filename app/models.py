"""领域模型。"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class TermBank:
    id: int
    name: str
    description: str = ""
    enabled: bool = True
    term_count: int = 0
    sort_order: int = 0
    created_at: str = ""
    updated_at: str = ""
    builtin: bool = False

    @classmethod
    def from_row(cls, row: Any) -> "TermBank":
        keys = row.keys()
        return cls(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            enabled=bool(row["enabled"]),
            term_count=row["term_count"] if "term_count" in keys else 0,
            sort_order=row["sort_order"] if "sort_order" in keys else 0,
            created_at=row["created_at"] if "created_at" in keys else "",
            updated_at=row["updated_at"] if "updated_at" in keys else "",
            builtin=bool(row["builtin"]) if "builtin" in keys else False,
        )


@dataclass
class Term:
    id: int
    bank_id: int
    src: str
    dst: str
    aliases: str = ""
    note: str = ""
    domain: str = ""
    case_sensitive: bool = False
    whole_word: bool = True
    enabled: bool = True
    priority: int = 0
    created_at: str = ""
    updated_at: str = ""
    bank_name: str = ""

    @property
    def alias_list(self) -> list[str]:
        return [a.strip() for a in self.aliases.replace("，", ",").split(",") if a.strip()]

    @classmethod
    def from_row(cls, row: Any) -> "Term":
        keys = row.keys()
        return cls(
            id=row["id"],
            bank_id=row["bank_id"],
            src=row["src"],
            dst=row["dst"],
            aliases=row["aliases"] or "",
            note=row["note"] or "",
            domain=row["domain"] or "",
            case_sensitive=bool(row["case_sensitive"]),
            whole_word=bool(row["whole_word"]),
            enabled=bool(row["enabled"]),
            priority=row["priority"] or 0,
            created_at=row["created_at"] if "created_at" in keys else "",
            updated_at=row["updated_at"] if "updated_at" in keys else "",
            bank_name=(row["bank_name"] or "") if "bank_name" in keys else "",
        )


@dataclass
class TMEntry:
    id: int
    src: str
    dst: str
    src_lang: str = ""
    tgt_lang: str = ""
    quality: float = 1.0
    hits: int = 0
    created_at: str = ""
    updated_at: str = ""
    origin: str = "legacy"
    occurrences: int = 1
    last_used_at: str = ""
    last_seen_at: str = ""
    reviewed_at: str = ""

    @classmethod
    def from_row(cls, row: Any) -> "TMEntry":
        keys = row.keys()
        return cls(
            id=row["id"],
            src=row["src"],
            dst=row["dst"],
            src_lang=row["src_lang"] or "",
            tgt_lang=row["tgt_lang"] or "",
            quality=float(row["quality"] or 1.0),
            hits=row["hits"] or 0,
            created_at=row["created_at"] if "created_at" in keys else "",
            updated_at=row["updated_at"] if "updated_at" in keys else "",
            origin=(row["origin"] or "legacy") if "origin" in keys else "legacy",
            occurrences=int(row["occurrences"] or 1) if "occurrences" in keys else 1,
            last_used_at=(row["last_used_at"] or "") if "last_used_at" in keys else "",
            last_seen_at=(row["last_seen_at"] or "") if "last_seen_at" in keys else "",
            reviewed_at=(row["reviewed_at"] or "") if "reviewed_at" in keys else "",
        )


@dataclass
class TMCandidate:
    """待审核的自动学习候选。"""

    id: int
    src: str
    dst: str
    src_lang: str = ""
    tgt_lang: str = ""
    quality: float = 1.0
    occurrences: int = 1
    asr_confidence: float | None = None
    asr_avg_logprob: float | None = None
    asr_no_speech_prob: float | None = None
    duration_s: float = 0.0
    chars: int = 0
    mt_model: str = ""
    asr_model: str = ""
    terms: list[dict[str, str]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    session_id: str | None = None
    status: str = "pending"
    first_seen_at: str = ""
    last_seen_at: str = ""
    reviewed_at: str = ""
    ai_state: str = "none"
    ai_decision: str = ""
    ai_score: float | None = None
    ai_issues: list[str] = field(default_factory=list)
    ai_suggested_dst: str = ""
    ai_reason: str = ""
    ai_model: str = ""
    ai_prompt_version: str = ""
    ai_reviewed_at: str = ""
    ai_latency_ms: int = 0

    @classmethod
    def from_row(cls, row: Any) -> "TMCandidate":
        keys = row.keys()

        def _json(value: Any, fallback: Any) -> Any:
            if not value:
                return fallback
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                return fallback
            return parsed if isinstance(parsed, type(fallback)) else fallback

        def _number(name: str) -> float | None:
            if name not in keys or row[name] is None:
                return None
            try:
                return float(row[name])
            except (TypeError, ValueError):
                return None

        return cls(
            id=int(row["id"]),
            src=row["src"] or "",
            dst=row["dst"] or "",
            src_lang=row["src_lang"] or "",
            tgt_lang=row["tgt_lang"] or "",
            quality=float(row["quality"] or 1.0),
            occurrences=int(row["occurrences"] or 1),
            asr_confidence=_number("asr_confidence"),
            asr_avg_logprob=_number("asr_avg_logprob"),
            asr_no_speech_prob=_number("asr_no_speech_prob"),
            duration_s=float(row["duration_s"] or 0.0),
            chars=int(row["chars"] or 0),
            mt_model=row["mt_model"] or "",
            asr_model=row["asr_model"] or "",
            terms=_json(row["terms_json"] if "terms_json" in keys else "", []),
            flags=_json(row["flags_json"] if "flags_json" in keys else "", []),
            session_id=(row["session_id"] or None) if "session_id" in keys else None,
            status=row["status"] or "pending",
            first_seen_at=row["first_seen_at"] or "",
            last_seen_at=row["last_seen_at"] or "",
            reviewed_at=row["reviewed_at"] or "",
            ai_state=row["ai_state"] or "none",
            ai_decision=row["ai_decision"] or "",
            ai_score=_number("ai_score"),
            ai_issues=_json(row["ai_issues_json"] if "ai_issues_json" in keys else "", []),
            ai_suggested_dst=row["ai_suggested_dst"] or "",
            ai_reason=row["ai_reason"] or "",
            ai_model=row["ai_model"] or "",
            ai_prompt_version=row["ai_prompt_version"] or "",
            ai_reviewed_at=row["ai_reviewed_at"] or "",
            ai_latency_ms=int(row["ai_latency_ms"] or 0),
        )

    @property
    def ai_label(self) -> str:
        if self.ai_state == "queued":
            return "排队中"
        if self.ai_state == "running":
            return "审核中"
        if self.ai_state == "error":
            return "AI 失败"
        if self.ai_state != "done":
            return "未审核"
        labels = {"approve": "建议通过", "needs_human": "需人工", "reject": "建议拒绝"}
        return labels.get(self.ai_decision, "待判定")


@dataclass
class Session:
    id: str
    started_at: str
    ended_at: str | None = None
    title: str = ""
    source_lang: str = "auto"
    target_lang: str = "zh"
    audio_source: str = ""
    asr_model: str = ""
    segment_count: int = 0
    duration_s: float = 0.0
    avg_latency_ms: float = 0.0
    status: str = "running"

    @classmethod
    def from_row(cls, row: Any) -> "Session":
        return cls(
            id=row["id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            title=row["title"] or "",
            source_lang=row["source_lang"] or "auto",
            target_lang=row["target_lang"] or "zh",
            audio_source=row["audio_source"] or "",
            asr_model=row["asr_model"] or "",
            segment_count=row["segment_count"] or 0,
            duration_s=float(row["duration_s"] or 0.0),
            avg_latency_ms=float(row["avg_latency_ms"] or 0.0),
            status=row["status"] or "done",
        )


@dataclass
class SegmentRecord:
    id: str
    session_id: str
    seq: int
    t_start: float
    t_end: float
    src: str = ""
    dst: str = ""
    asr_ms: float = 0.0
    ttfb_ms: float = 0.0
    total_ms: float = 0.0
    terms: str = ""
    via_tm: bool = False
    created_at: str = ""

    @classmethod
    def from_row(cls, row: Any) -> "SegmentRecord":
        return cls(
            id=row["id"],
            session_id=row["session_id"],
            seq=row["seq"],
            t_start=float(row["t_start"] or 0),
            t_end=float(row["t_end"] or 0),
            src=row["src"] or "",
            dst=row["dst"] or "",
            asr_ms=float(row["asr_ms"] or 0),
            ttfb_ms=float(row["ttfb_ms"] or 0),
            total_ms=float(row["total_ms"] or 0),
            terms=row["terms"] or "",
            via_tm=bool(row["via_tm"]),
            created_at=row["created_at"] if "created_at" in row.keys() else "",
        )


@dataclass
class LiveSegment:
    """界面上的一条实时字幕。"""

    id: str
    seq: int
    t_start: float
    t_end: float = 0.0
    src: str = ""
    dst: str = ""
    state: str = "listening"  # listening / transcribing / translating / done / error / dropped
    asr_ms: float = 0.0
    ttfb_ms: float = 0.0
    total_ms: float = 0.0
    terms: list[dict[str, str]] = field(default_factory=list)
    via_tm: bool = False
    error: str = ""
    created_mono: float = field(default_factory=time.monotonic)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "seq": self.seq,
            "t_start": self.t_start,
            "t_end": self.t_end,
            "src": self.src,
            "dst": self.dst,
            "state": self.state,
            "asr_ms": self.asr_ms,
            "ttfb_ms": self.ttfb_ms,
            "total_ms": self.total_ms,
            "terms": list(self.terms),
            "via_tm": self.via_tm,
            "error": self.error,
        }
