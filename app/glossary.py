"""术语匹配：Aho-Corasick 内存自动机，按句命中，微秒级。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable

try:
    import ahocorasick

    _HAS_AHO = True
except ImportError:  # pragma: no cover - 回退路径
    _HAS_AHO = False

log = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[A-Za-z0-9_]")


def _is_word_char(ch: str) -> bool:
    return bool(ch) and bool(_WORD_RE.match(ch))


@dataclass(frozen=True)
class GlossaryTerm:
    term_id: int
    bank_id: int
    bank_name: str
    src: str
    dst: str
    aliases: tuple[str, ...]
    case_sensitive: bool
    whole_word: bool
    priority: int
    domain: str = ""

    @property
    def patterns(self) -> list[str]:
        values = [self.src, *self.aliases]
        return [v for v in dict.fromkeys(v.strip() for v in values if v and v.strip())]

    @property
    def has_latin_edge(self) -> bool:
        return any(c.isascii() and (c.isalnum() or c == "_") for c in (self.src[:1] + self.src[-1:]))


@dataclass(frozen=True)
class TermHit:
    term: GlossaryTerm
    start: int
    end: int
    matched: str

    def as_dict(self) -> dict[str, str]:
        return {
            "src": self.term.src,
            "dst": self.term.dst,
            "matched": self.matched,
            "bank": self.term.bank_name,
            "domain": self.term.domain,
        }


def terms_from_rows(terms: Iterable[Any]) -> list[GlossaryTerm]:
    result: list[GlossaryTerm] = []
    for t in terms:
        result.append(
            GlossaryTerm(
                term_id=int(t.id),
                bank_id=int(t.bank_id),
                bank_name=getattr(t, "bank_name", "") or "",
                src=t.src.strip(),
                dst=t.dst.strip(),
                aliases=tuple(t.alias_list),
                case_sensitive=bool(t.case_sensitive),
                whole_word=bool(t.whole_word),
                priority=int(t.priority or 0),
                domain=t.domain or "",
            )
        )
    return result


class GlossaryMatcher:
    """把全部启用术语编译进一个自动机；一次扫描整句。"""

    def __init__(self, terms: Iterable[GlossaryTerm] | None = None) -> None:
        self._ci: dict[str, list[GlossaryTerm]] = {}
        self._cs: dict[str, list[GlossaryTerm]] = {}
        self._ci_auto = None
        self._cs_auto = None
        self._naive: list[GlossaryTerm] = []
        self.build(terms or [])

    @property
    def size(self) -> int:
        return len({t.term_id for group in self._ci.values() for t in group} | {
            t.term_id for group in self._cs.values() for t in group
        })

    def build(self, terms: Iterable[GlossaryTerm]) -> None:
        self._ci.clear()
        self._cs.clear()
        self._naive = list(terms)
        for term in self._naive:
            for pattern in term.patterns:
                bucket = self._cs if term.case_sensitive else self._ci
                key = pattern if term.case_sensitive else pattern.lower()
                bucket.setdefault(key, []).append(term)

        if _HAS_AHO:
            self._ci_auto = self._make_automaton(self._ci)
            self._cs_auto = self._make_automaton(self._cs)
        else:
            self._ci_auto = self._cs_auto = None

    @staticmethod
    def _make_automaton(mapping: dict[str, list[GlossaryTerm]]):
        if not mapping:
            return None
        auto = ahocorasick.Automaton()
        for key, values in mapping.items():
            auto.add_word(key, (key, values))
        auto.make_automaton()
        return auto

    def match(self, text: str, max_hits: int = 60) -> list[TermHit]:
        if not text or not self._naive:
            return []
        hits: list[TermHit] = []
        if self._ci_auto is not None:
            lowered = text.lower()
            for end, (key, values) in self._ci_auto.iter(lowered):
                start = end - len(key) + 1
                for term in values:
                    if self._accept(term, text, start, end + 1):
                        hits.append(TermHit(term, start, end + 1, text[start : end + 1]))
        elif self._ci:
            hits.extend(self._naive_scan(text, case_sensitive=False))

        if self._cs_auto is not None:
            for end, (key, values) in self._cs_auto.iter(text):
                start = end - len(key) + 1
                for term in values:
                    if self._accept(term, text, start, end + 1):
                        hits.append(TermHit(term, start, end + 1, text[start : end + 1]))
        elif self._cs:
            hits.extend(self._naive_scan(text, case_sensitive=True))

        # 同一位置优先长词 / 原文精确命中 / 高优先级；去重
        hits.sort(
            key=lambda h: (
                h.start,
                -(h.end - h.start),
                0 if h.matched.lower() == h.term.src.lower() else 1,
                -h.term.priority,
            )
        )
        deduped: list[TermHit] = []
        seen: set[tuple[int, int, int]] = set()
        for hit in hits:
            key = (hit.term.term_id, hit.start, hit.end)
            if key in seen:
                continue
            seen.add(key)
            if any(
                hit.start < other.end and other.start < hit.end
                and hit.term.term_id != other.term.term_id
                for other in deduped
            ):
                continue
            deduped.append(hit)
            if len(deduped) >= max_hits:
                break
        return deduped

    @staticmethod
    def _accept(term: GlossaryTerm, text: str, start: int, end: int) -> bool:
        if not term.whole_word:
            return True
        if not term.has_latin_edge:
            return True
        before = text[start - 1] if start > 0 else ""
        after = text[end] if end < len(text) else ""
        if before and _is_word_char(before) and (term.src[:1].isascii() and _is_word_char(term.src[:1])):
            return False
        if after and _is_word_char(after) and (term.src[-1:].isascii() and _is_word_char(term.src[-1:])):
            return False
        return True

    def _naive_scan(self, text: str, case_sensitive: bool) -> list[TermHit]:
        haystack = text if case_sensitive else text.lower()
        hits: list[TermHit] = []
        for term in self._naive:
            if term.case_sensitive != case_sensitive:
                continue
            for pattern in term.patterns:
                needle = pattern if case_sensitive else pattern.lower()
                start = 0
                while True:
                    idx = haystack.find(needle, start)
                    if idx < 0:
                        break
                    if self._accept(term, text, idx, idx + len(needle)):
                        hits.append(TermHit(term, idx, idx + len(needle), text[idx : idx + len(needle)]))
                    start = idx + max(1, len(needle))
        return hits


def render_glossary(hits: Iterable[TermHit], max_terms: int = 24) -> str:
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        key = (hit.term.src.lower(), hit.term.dst.lower())
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {hit.term.src} → {hit.term.dst}")
        if len(lines) >= max_terms:
            break
    return "\n".join(lines)


def hits_to_dicts(hits: Iterable[TermHit]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for hit in hits:
        key = (hit.term.src.lower(), hit.term.dst.lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(hit.as_dict())
    return result


def missing_terms(hits: Iterable[TermHit], translated: str) -> list[str]:
    """检查译文中是否出现了术语目标词；返回缺失的原文术语。"""
    text = translated.lower()
    missing: list[str] = []
    for hit in hits:
        raw = hit.term.dst.strip()
        pieces = [raw, re.sub(r"[（(].*?[）)]", "", raw)]
        pieces += re.findall(r"[（(](.*?)[）)]", raw)
        variants: list[str] = []
        for piece in pieces:
            variants.extend(
                v.strip().lower()
                for v in re.split(r"[/；;、]", piece)
                if v.strip()
            )
        if variants and not any(v in text for v in variants):
            missing.append(hit.term.src)
    return missing


def build_matcher(db) -> GlossaryMatcher:
    try:
        return GlossaryMatcher(terms_from_rows(db.active_terms()))
    except Exception:  # pragma: no cover
        log.exception("构建术语自动机失败")
        return GlossaryMatcher([])
