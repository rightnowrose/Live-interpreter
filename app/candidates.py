"""自动学习候选的规则过滤与质量评分。

这里的所有判断只依赖本地文本和 ASR 元数据，不会发起网络请求。
候选只有经过人工（或显式开启的 AI 自动采纳）才会进入正式翻译记忆。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

_KANA = re.compile(r"[\u3040-\u30ff]")
_HAN = re.compile(r"[\u3400-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")
_HANGUL = re.compile(r"[\uac00-\ud7af]")
_DIGITS = re.compile(r"\d+")
_FILLER_TOKEN = (
    r"(?:えー+|えっと+|あのー*|そのー*|そうですね|はい+|うん+|まあ+|"
    r"ちょっと|なんか|こう|あれ|それ|どれ|えっ+)"
)
_FILLERS = re.compile(rf"^(?:{_FILLER_TOKEN}[。！？、,.!?…\s]*)+$")
_PUNCT = re.compile(r"[\s,.!?;:，。！？；：、…\"'“”‘’（）()\[\]【】〈〉《》\-—~～]+")


@dataclass
class CandidateDraft:
    src: str
    dst: str
    src_lang: str
    tgt_lang: str
    quality: float
    flags: list[str] = field(default_factory=list)
    terms: list[dict[str, str]] = field(default_factory=list)
    duration_s: float = 0.0
    chars: int = 0
    mt_model: str = ""
    asr_model: str = ""
    session_id: str | None = None
    asr_avg_logprob: float | None = None
    asr_no_speech_prob: float | None = None


def _letters(text: str) -> int:
    return len(_PUNCT.sub("", text))


def _term_list(hits: Iterable[Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for hit in hits or []:
        term = getattr(hit, "term", None)
        src = getattr(term, "src", "")
        dst = getattr(term, "dst", "")
        if not src or not dst or src in seen:
            continue
        seen.add(src)
        result.append({"src": src, "dst": dst})
    return result


def _repetition(text: str) -> bool:
    compact = _PUNCT.sub("", text)
    if len(compact) < 8:
        return False
    for size in range(4, min(12, len(compact) // 2 + 1)):
        for index in range(0, len(compact) - size * 2 + 1):
            chunk = compact[index : index + size]
            if compact[index + size : index + size * 2] == chunk:
                return True
    return False


def _target_language_ok(dst: str, tgt_lang: str) -> bool:
    letters = max(1, _letters(dst))
    if tgt_lang.startswith("zh"):
        chinese = len(_HAN.findall(dst))
        kana = len(_KANA.findall(dst))
        return chinese >= 2 and chinese / letters >= 0.45 and kana <= max(1, chinese * 0.2)
    if tgt_lang == "ja":
        japanese = len(_HAN.findall(dst)) + len(_KANA.findall(dst))
        return japanese >= 2 and japanese / letters >= 0.45
    if tgt_lang == "ko":
        hangul = len(_HANGUL.findall(dst))
        return hangul >= 2 and hangul / letters >= 0.45
    return len(_LATIN.findall(dst)) >= 2


def evaluate_candidate(
    src: str,
    dst: str,
    src_lang: str,
    tgt_lang: str,
    hits: Iterable[Any] = (),
    *,
    duration_s: float = 0.0,
    mt_model: str = "",
    asr_model: str = "",
    session_id: str | None = None,
    asr_avg_logprob: float | None = None,
    asr_no_speech_prob: float | None = None,
    min_chars: int = 6,
    max_chars: int = 80,
) -> CandidateDraft | None:
    """返回候选；明显的噪声直接丢弃（None）。"""
    src = (src or "").strip()
    dst = (dst or "").strip()
    if not src or not dst:
        return None
    if not (min_chars <= len(src) <= max_chars):
        return None
    if _FILLERS.match(src):
        return None
    if not (_HAN.search(src) or _KANA.search(src) or _LATIN.search(src) or _HANGUL.search(src)):
        return None
    if not _target_language_ok(dst, tgt_lang):
        return None

    src_letters = max(1, _letters(src))
    dst_letters = max(1, _letters(dst))
    ratio = dst_letters / src_letters
    flags: list[str] = []
    quality = 1.0

    if ratio < 0.35 or ratio > 2.8:
        flags.append("length_ratio")
        quality -= 0.08
    if _PUNCT.sub("", src).lower() == _PUNCT.sub("", dst).lower():
        return None
    if len(src) >= 8 and _PUNCT.sub("", dst).startswith(_PUNCT.sub("", src)[: max(8, len(src) // 2)]):
        return None
    if _repetition(dst):
        flags.append("repetition")
        quality -= 0.12

    source_numbers = set(_DIGITS.findall(src))
    if source_numbers and not source_numbers.issubset(set(_DIGITS.findall(dst))):
        flags.append("number_mismatch")
        quality -= 0.10

    terms = _term_list(hits)
    for term in terms:
        if term["dst"] and term["dst"] not in dst:
            flags.append("missing_term")
            quality -= 0.16
            break
    if terms:
        flags.append("term_hit")

    if asr_avg_logprob is not None and asr_avg_logprob < -0.6:
        flags.append("low_asr")
        quality -= 0.15
    if asr_no_speech_prob is not None and asr_no_speech_prob > 0.4:
        flags.append("low_asr")
        quality -= 0.15
    if asr_avg_logprob is None and asr_no_speech_prob is None:
        flags.append("asr_unscored")
        quality -= 0.03

    if duration_s > 0 and (duration_s < 0.6 or duration_s > 25):
        flags.append("duration")
        quality -= 0.06

    return CandidateDraft(
        src=src,
        dst=dst,
        src_lang=src_lang,
        tgt_lang=tgt_lang,
        quality=max(0.0, min(1.0, quality)),
        flags=flags,
        terms=terms,
        duration_s=float(duration_s or 0.0),
        chars=len(src),
        mt_model=mt_model,
        asr_model=asr_model,
        session_id=session_id,
        asr_avg_logprob=asr_avg_logprob,
        asr_no_speech_prob=asr_no_speech_prob,
    )


def auto_approvable(
    candidate: Any,
    ai_decision: str,
    ai_score: float,
    ai_issues: Iterable[str],
    *,
    min_score: float = 0.9,
    min_occurrences: int = 2,
) -> bool:
    """仅为显式开启自动采纳时使用；默认配置不会走这里。"""
    if ai_decision != "approve" or float(ai_score) < min_score:
        return False
    if list(ai_issues):
        return False
    flags = set(getattr(candidate, "flags", []) or [])
    blocking = {
        "missing_term",
        "duplicate",
        "low_asr",
        "asr_unscored",
        "length_ratio",
        "number_mismatch",
        "repetition",
        "duration",
    }
    if flags & blocking:
        return False
    if int(getattr(candidate, "quality", 0) * 100) < 85:
        return False
    if int(getattr(candidate, "occurrences", 1)) < min_occurrences and "term_hit" not in flags:
        return False
    return True
