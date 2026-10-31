"""术语库 / 语料库文件导入。"""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SRC_HEADERS = {"src", "source", "term", "原文", "术语", "原词", "源词"}
_DST_HEADERS = {"dst", "target", "translation", "译文", "译法", "目标", "翻译"}
_ALIAS_HEADERS = {"aliases", "alias", "别名", "变体", "同义词"}
_DOMAIN_HEADERS = {"domain", "领域", "分类", "category"}
_NOTE_HEADERS = {"note", "notes", "备注", "说明", "comment"}


def _normalize(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _map_headers(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, header in enumerate(headers):
        key = header.strip().lower()
        if key in _SRC_HEADERS and "src" not in mapping:
            mapping["src"] = index
        elif key in _DST_HEADERS and "dst" not in mapping:
            mapping["dst"] = index
        elif key in _ALIAS_HEADERS and "aliases" not in mapping:
            mapping["aliases"] = index
        elif key in _DOMAIN_HEADERS and "domain" not in mapping:
            mapping["domain"] = index
        elif key in _NOTE_HEADERS and "note" not in mapping:
            mapping["note"] = index
    if "src" not in mapping or "dst" not in mapping:
        mapping.setdefault("src", 0)
        mapping.setdefault("dst", 1)
        mapping.setdefault("aliases", 2 if len(headers) > 2 else -1)
        mapping.setdefault("domain", 3 if len(headers) > 3 else -1)
        mapping.setdefault("note", 4 if len(headers) > 4 else -1)
    return mapping


def _rows_to_dicts(rows: list[list[Any]], has_header: bool = True) -> list[dict[str, str]]:
    if not rows:
        return []
    headers = [_normalize(v) for v in rows[0]] if has_header else []
    mapping = _map_headers(headers)
    start = 1 if has_header else 0
    result: list[dict[str, str]] = []
    for row in rows[start:]:
        if not row:
            continue

        def get(key: str) -> str:
            index = mapping.get(key, -1)
            if 0 <= index < len(row):
                return _normalize(row[index])
            return ""

        src, dst = get("src"), get("dst")
        if not src or not dst:
            continue
        result.append(
            {
                "src": src,
                "dst": dst,
                "aliases": get("aliases"),
                "domain": get("domain"),
                "note": get("note"),
            }
        )
    return result


def _read_csv(path: Path) -> list[dict[str, str]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "replace")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)
    if not rows:
        return []
    return _rows_to_dicts(rows, has_header=True)


def _read_xlsx(path: Path) -> list[dict[str, str]]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = [list(row) for row in ws.iter_rows(values_only=True)]
    wb.close()
    return _rows_to_dicts(rows, has_header=True)


def _read_json(path: Path) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("terms") or data.get("items") or data.get("data") or []
    if not isinstance(data, list):
        return []
    result: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        src = _normalize(item.get("src") or item.get("source") or item.get("原文"))
        dst = _normalize(item.get("dst") or item.get("target") or item.get("译文"))
        if not src or not dst:
            continue
        result.append(
            {
                "src": src,
                "dst": dst,
                "aliases": _normalize(item.get("aliases") or item.get("别名")),
                "domain": _normalize(item.get("domain") or item.get("领域")),
                "note": _normalize(item.get("note") or item.get("备注")),
            }
        )
    return result


def read_term_file(path: Path | str) -> list[dict[str, str]]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv", ".txt"):
        return _read_csv(path)
    if suffix in (".xlsx", ".xlsm"):
        return _read_xlsx(path)
    if suffix == ".json":
        return _read_json(path)
    raise ValueError(f"不支持的文件类型：{suffix}")


def read_tm_file(path: Path | str) -> list[dict[str, str]]:
    return read_term_file(path)
