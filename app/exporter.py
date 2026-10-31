"""同传记录导出：SRT / TXT / Markdown / JSON / CSV / XLSX。"""

from __future__ import annotations

import csv
import json
import logging
import re
from pathlib import Path
from typing import Iterable

from .models import SegmentRecord, Session, TMEntry, Term

log = logging.getLogger(__name__)

FORMATS = {
    "srt": "SRT 字幕",
    "txt": "纯文本",
    "md": "Markdown",
    "json": "JSON",
    "csv": "CSV 表格",
    "xlsx": "Excel 工作簿",
}


def safe_filename(name: str, fallback: str = "transcript") -> str:
    value = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name).strip(" ._")
    return value[:80] or fallback


def suggest_filename(session: Session, fmt: str) -> str:
    stamp = (session.started_at or "").replace(":", "").replace("-", "").replace("T", "_")[:15]
    title = safe_filename(session.title or "同传记录")
    return f"{stamp}_{title}.{fmt}"


def _srt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _mode_lines(seg: SegmentRecord, mode: str) -> list[str]:
    if mode == "src":
        return [seg.src] if seg.src else []
    if mode == "dst":
        return [seg.dst] if seg.dst else []
    lines = []
    if seg.src:
        lines.append(seg.src)
    if seg.dst:
        lines.append(seg.dst)
    return lines


def export_session(
    session: Session,
    segments: Iterable[SegmentRecord],
    path: Path | str,
    fmt: str,
    mode: str = "both",
    include_meta: bool = True,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = list(segments)
    fmt = fmt.lower()
    if fmt == "srt":
        text = _to_srt(records, mode)
    elif fmt == "txt":
        text = _to_txt(session, records, mode, include_meta)
    elif fmt == "md":
        text = _to_md(session, records, mode, include_meta)
    elif fmt == "json":
        text = _to_json(session, records)
    elif fmt == "csv":
        _to_csv(path, records)
        return path
    elif fmt == "xlsx":
        _to_xlsx(path, records, session)
        return path
    else:
        raise ValueError(f"不支持的导出格式：{fmt}")
    path.write_text(text, encoding="utf-8")
    return path


def _to_srt(records: list[SegmentRecord], mode: str) -> str:
    blocks: list[str] = []
    for index, seg in enumerate(records, start=1):
        lines = _mode_lines(seg, mode)
        if not lines:
            continue
        start = seg.t_start
        end = max(seg.t_end, start + 0.6)
        blocks.append(
            f"{index}\n{_srt_time(start)} --> {_srt_time(end)}\n" + "\n".join(lines)
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _to_txt(
    session: Session, records: list[SegmentRecord], mode: str, include_meta: bool
) -> str:
    out: list[str] = []
    if include_meta:
        out.append(f"同传记录：{session.title}")
        out.append(
            f"时间：{session.started_at}    时长：{_clock(session.duration_s)}    "
            f"语言：{session.source_lang} → {session.target_lang}"
        )
        out.append("=" * 60)
        out.append("")
    for seg in records:
        lines = _mode_lines(seg, mode)
        if not lines:
            continue
        out.append(f"[{_clock(seg.t_start)}]")
        out.extend(lines)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _to_md(
    session: Session, records: list[SegmentRecord], mode: str, include_meta: bool
) -> str:
    out: list[str] = []
    if include_meta:
        out.append(f"# {session.title or '同传记录'}")
        out.append("")
        out.append(
            f"- **开始时间**：{session.started_at}\n"
            f"- **时长**：{_clock(session.duration_s)}\n"
            f"- **语言**：{session.source_lang} → {session.target_lang}\n"
            f"- **片段数**：{session.segment_count}\n"
            f"- **平均端到端延迟**：{session.avg_latency_ms:.0f} ms"
        )
        out.append("")
        out.append("| 时间 | 原文 | 译文 | 延迟 |")
        out.append("| --- | --- | --- | --- |")
    for seg in records:
        if not seg.src and not seg.dst:
            continue
        src = seg.src.replace("|", "\\|")
        dst = seg.dst.replace("|", "\\|")
        if mode == "src":
            dst = ""
        elif mode == "dst":
            src = ""
        out.append(f"| {_clock(seg.t_start)} | {src} | {dst} | {seg.total_ms:.0f} ms |")
    return "\n".join(out) + "\n"


def _to_json(session: Session, records: list[SegmentRecord]) -> str:
    payload = {
        "title": session.title,
        "session": {
            "id": session.id,
            "started_at": session.started_at,
            "ended_at": session.ended_at,
            "duration_s": session.duration_s,
            "source_lang": session.source_lang,
            "target_lang": session.target_lang,
            "audio_source": session.audio_source,
            "asr_model": session.asr_model,
            "segment_count": session.segment_count,
            "avg_latency_ms": session.avg_latency_ms,
        },
        "segments": [
            {
                "seq": seg.seq,
                "start": seg.t_start,
                "end": seg.t_end,
                "src": seg.src,
                "dst": seg.dst,
                "asr_ms": seg.asr_ms,
                "ttfb_ms": seg.ttfb_ms,
                "total_ms": seg.total_ms,
                "via_tm": seg.via_tm,
                "terms": json.loads(seg.terms) if seg.terms else [],
            }
            for seg in records
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _to_csv(path: Path, records: list[SegmentRecord]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["序号", "开始(秒)", "结束(秒)", "原文", "译文", "ASR(ms)", "TTFB(ms)", "总延迟(ms)", "语料库", "术语"]
        )
        for seg in records:
            writer.writerow(
                [
                    seg.seq,
                    f"{seg.t_start:.2f}",
                    f"{seg.t_end:.2f}",
                    seg.src,
                    seg.dst,
                    f"{seg.asr_ms:.0f}",
                    f"{seg.ttfb_ms:.0f}",
                    f"{seg.total_ms:.0f}",
                    "是" if seg.via_tm else "",
                    seg.terms,
                ]
            )


def _to_xlsx(path: Path, records: list[SegmentRecord], session: Session) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "同传记录"
    headers = ["序号", "开始", "结束", "原文", "译文", "ASR(ms)", "TTFB(ms)", "总延迟(ms)", "语料库"]
    ws.append(headers)
    fill = PatternFill("solid", fgColor="1F2937")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center")
    for seg in records:
        ws.append(
            [
                seg.seq,
                _clock(seg.t_start),
                _clock(seg.t_end),
                seg.src,
                seg.dst,
                round(seg.asr_ms),
                round(seg.ttfb_ms),
                round(seg.total_ms),
                "是" if seg.via_tm else "",
            ]
        )
    widths = [6, 10, 10, 60, 60, 10, 10, 12, 8]
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"

    meta = wb.create_sheet("元数据")
    meta.append(["标题", session.title])
    meta.append(["开始时间", session.started_at])
    meta.append(["结束时间", session.ended_at or ""])
    meta.append(["时长(秒)", session.duration_s])
    meta.append(["语言", f"{session.source_lang} → {session.target_lang}"])
    meta.append(["音频源", session.audio_source])
    meta.append(["ASR 模型", session.asr_model])
    meta.append(["片段数", session.segment_count])
    meta.append(["平均延迟(ms)", session.avg_latency_ms])
    meta.column_dimensions["A"].width = 18
    meta.column_dimensions["B"].width = 60
    wb.save(path)


# ------------------------------------------------------------------ 术语库 / 语料库导出
def export_terms(terms: Iterable[Term], path: Path | str, fmt: str = "csv") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "src": t.src,
            "dst": t.dst,
            "aliases": t.aliases,
            "domain": t.domain,
            "note": t.note,
            "enabled": "1" if t.enabled else "0",
            "priority": t.priority,
        }
        for t in terms
    ]
    fmt = fmt.lower()
    if fmt == "json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    elif fmt == "xlsx":
        _rows_to_xlsx(rows, path, ["src", "dst", "aliases", "domain", "note", "enabled", "priority"])
    else:
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["src", "dst", "aliases", "domain", "note", "enabled", "priority"]
            )
            writer.writeheader()
            writer.writerows(rows)
    return path


def export_tm(entries: Iterable[TMEntry], path: Path | str, fmt: str = "csv") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"src": e.src, "dst": e.dst, "src_lang": e.src_lang, "tgt_lang": e.tgt_lang, "hits": e.hits}
        for e in entries
    ]
    fmt = fmt.lower()
    if fmt == "json":
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    elif fmt == "xlsx":
        _rows_to_xlsx(rows, path, ["src", "dst", "src_lang", "tgt_lang", "hits"])
    else:
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["src", "dst", "src_lang", "tgt_lang", "hits"]
            )
            writer.writeheader()
            writer.writerows(rows)
    return path


def _rows_to_xlsx(rows: list[dict], path: Path, headers: list[str]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F2937")
    for row in rows:
        ws.append([row.get(h, "") for h in headers])
    for index, header in enumerate(headers, start=1):
        width = max(12, min(60, max(len(str(r.get(header, ""))) for r in rows) + 2 if rows else 12))
        ws.column_dimensions[chr(64 + index)].width = width
    wb.save(path)
