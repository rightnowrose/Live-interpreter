"""核心逻辑自检（无需音频/API）。"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="si_selftest_"))
os.environ["SI_DATA_DIR"] = str(TMP)

from app import exporter, secret  # noqa: E402
from app.config import CONFIG_VERSION, ConfigStore  # noqa: E402
from app.db import Database  # noqa: E402
from app.glossary import GlossaryMatcher, render_glossary, terms_from_rows  # noqa: E402
from app.tm import TranslationMemory  # noqa: E402
from app.translator import build_messages  # noqa: E402


def check(condition, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print("ok -", message)


def main() -> None:
    config = ConfigStore()
    check(config.settings.asr.model == "parakeet-tdt-0.6b-ja", "默认配置")
    check(
        config.settings.translate.model == "deepseek-flash"
        and not config.settings.translate.thinking,
        "默认 deepseek-flash 且关闭深度思考",
    )
    check(
        config.settings.translate.local_model == "hy-mt-1.8b-q4"
        and config.settings.translate.provider == "deepseek",
        "默认保留 DeepSeek，并提供本地 HY-MT1.5 选项",
    )

    legacy_path = TMP / "legacy_config.json"
    legacy_path.write_text(
        json.dumps(
            {
                "version": 1,
                "translate": {"model": "deepseek-chat"},
                "overlay": {"past_lines": 1},
            }
        ),
        encoding="utf-8",
    )
    migrated = ConfigStore(legacy_path)
    check(
        migrated.settings.translate.model == "deepseek-flash"
        and not migrated.settings.translate.thinking
        and migrated.settings.version == CONFIG_VERSION
        and migrated.settings.overlay.past_lines == 6,
        "旧配置迁移到 deepseek-flash 与 5 句历史",
    )

    config.set_api_key("sk-test-123456")
    check(config.api_key == "sk-test-123456", "API Key DPAPI 往返")
    check(ConfigStore().api_key == "sk-test-123456", "重新读取 API Key")

    db = Database()
    banks = db.list_banks()
    base = next((bank for bank in banks if bank.builtin), None)
    check(base is not None and base.term_count >= 100, "内置基础术语库与种子术语")
    check(
        any(bank.name == "默认术语库" and bank.term_count == 6 for bank in banks),
        "默认术语库与种子术语",
    )
    check(base is not None and base.enabled, "内置基础术语库默认参与匹配")

    bank_id = db.create_bank("医学")
    db.add_term(bank_id, "myocardial infarction", "心肌梗死", aliases="MI", domain="医学")
    db.add_term(bank_id, "MI", "心肌梗死", whole_word=True)
    terms = db.active_terms()
    matcher = GlossaryMatcher(terms_from_rows(terms))
    hits = matcher.match("The patient had a myocardial infarction (MI) yesterday.")
    labels = {h.term.src for h in hits}
    check("myocardial infarction" in labels and "MI" in labels, "术语 Aho-Corasick 命中")
    base_hits = matcher.match("配信でスパチャを読みます。")
    base_labels = {h.term.src for h in base_hits}
    check("配信" in base_labels and "スパチャ" in base_labels, "内置基础术语参与匹配")
    check(not matcher.match("ASRfoo"), "全词边界")
    block = render_glossary(hits)
    check("心肌梗死" in block, "术语 prompt 渲染")

    msg = build_messages(
        "The patient had a myocardial infarction.",
        hits,
        [("Latency matters.", "延迟很重要。")],
        config.settings.translate,
    )
    check("心肌梗死" in msg[0]["content"], "翻译 prompt 注入命中术语")
    check("Terminal" not in msg[0]["content"], "prompt 不含无关内容")

    db.upsert_tm("The latency is mainly determined by VAD.", "延迟主要由 VAD 决定。", tgt_lang="zh")
    db.upsert_tm("We should keep thinking mode disabled.", "应保持 thinking 模式关闭。", tgt_lang="zh")
    tm = TranslationMemory(db, "zh")
    exact = tm.lookup("The latency is mainly determined by VAD.")
    check(exact is not None and exact.exact, "语料库精确命中")
    fuzzy = tm.lookup("The latency is mainly determined by VAD")
    check(fuzzy is not None, "语料库去标点命中")
    near = tm.lookup("The latency is mainly determined by the VAD setting.")
    check(near is None or near.score < 0.99, "模糊命中分数")
    check(tm.lookup("Completely different sentence.") is None, "无关句不命中")

    db.create_session("s1", "测试", "en", "zh", "系统声音", "large-v3-turbo")
    db.add_segment("s1", "seg1", 1, 0.0, 2.0, "Hello world.", 300, [])
    db.update_segment_translation("seg1", "你好，世界。", 200, 700, False)
    db.add_segment("s1", "seg2", 2, 2.5, 5.0, "This is a test.", 280, [])
    db.update_segment_translation("seg2", "这是一次测试。", 180, 650, True)
    db.finish_session("s1", 12.5)
    session = db.get_session("s1")
    check(session is not None and session.segment_count == 2, "会话落盘")
    check(abs(session.avg_latency_ms - 675) < 1, "平均延迟")
    segments = db.session_segments("s1")
    check(len(segments) == 2 and segments[1].via_tm, "片段译文")

    out = TMP / "exports"
    for fmt in ("srt", "txt", "md", "json", "csv", "xlsx"):
        path = exporter.export_session(session, segments, out / f"test.{fmt}", fmt, "both")
        check(path.exists() and path.stat().st_size > 0, f"导出 {fmt}")
    srt = (out / "test.srt").read_text(encoding="utf-8")
    check("00:00:00,000 --> 00:00:02,000" in srt and "你好，世界" in srt, "SRT 时间轴")

    exported = exporter.export_terms(db.list_terms(bank_id), out / "terms.csv", "csv")
    check(exported.exists(), "术语库导出")
    from app.importers import read_term_file

    rows = read_term_file(exported)
    check(len(rows) >= 2 and rows[0]["src"], "术语库 CSV 再导入")

    check(secret.decrypt(secret.encrypt("abc")) == "abc", "加密往返")

    db.close()
    shutil.rmtree(TMP, ignore_errors=True)
    print("\nALL CORE TESTS PASSED")


if __name__ == "__main__":
    main()
