"""候选审核 / 数据库迁移 / 语料检索的回归测试。"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.candidates import auto_approvable, evaluate_candidate
from app.db import Database
from app.tm import TranslationMemory


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="si_candidates_"))
    db = Database(root / "test.db")
    assert db.candidate_count() == 0
    columns = {row["name"] for row in db.conn.execute("PRAGMA table_info(tm_candidates)")}
    for name in (
        "ai_state",
        "ai_decision",
        "ai_score",
        "ai_issues_json",
        "ai_suggested_dst",
        "ai_reason",
        "ai_model",
        "ai_prompt_version",
        "ai_latency_ms",
    ):
        assert name in columns, name
    print("ok - 数据库 v2 候选表与 AI 字段")

    legacy_path = root / "legacy.db"
    legacy = sqlite3.connect(legacy_path)
    legacy.executescript(
        """
        CREATE TABLE tm (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            src TEXT NOT NULL, src_key TEXT NOT NULL, dst TEXT NOT NULL,
            src_lang TEXT NOT NULL DEFAULT '', tgt_lang TEXT NOT NULL DEFAULT '',
            quality REAL NOT NULL DEFAULT 1.0, hits INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        INSERT INTO tm(src,src_key,dst,src_lang,tgt_lang,quality,hits,created_at,updated_at)
        VALUES('旧句子','旧句子','旧译文','ja','zh',1.0,0,'2026-01-01','2026-01-01');
        PRAGMA user_version=1;
        """
    )
    legacy.commit()
    legacy.close()
    migrated = Database(legacy_path)
    assert migrated.conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert any(e.src == "旧句子" and e.origin == "legacy" for e in migrated.list_tm("zh"))
    assert migrated.candidate_count(status="pending") == 0
    migrated.close()
    print("ok - v1 数据库迁移到 v3")

    assert evaluate_candidate("えー、あの、", "呃，那个。", "ja", "zh") is None
    assert evaluate_candidate("はい", "是。", "ja", "zh") is None
    assert evaluate_candidate("これは十分に長い日本語の文章です。", "这是一句足够长的中文译文。", "ja", "zh") is not None
    print("ok - 规则硬拒绝与正常候选")

    draft = evaluate_candidate(
        "本日の会議では、新しい翻訳モデルの遅延について説明します。",
        "在今天的会议上，我们将说明新翻译模型的延迟问题。",
        "ja",
        "zh",
        [type("Hit", (), {"term": type("Term", (), {"src": "翻訳モデル", "dst": "翻译模型"})()})()],
        duration_s=3.2,
    )
    assert draft is not None and "term_hit" in draft.flags
    candidate_id = db.upsert_candidate(
        src=draft.src,
        dst=draft.dst,
        src_lang=draft.src_lang,
        tgt_lang=draft.tgt_lang,
        quality=draft.quality,
        occurrences=2,
        terms=draft.terms,
        flags=draft.flags,
        session_id=None,
    )
    assert candidate_id is not None
    assert db.candidate_count(status="pending") == 1
    print("ok - 候选写入与去重")

    db.save_ai_review(
        candidate_id,
        decision="approve",
        score=0.94,
        issues=[],
        suggested_dst="",
        reason="准确自然",
        model="deepseek-flash",
        prompt_version="v1",
        latency_ms=800,
    )
    reviewed = db.get_candidate(candidate_id)
    assert reviewed is not None and reviewed.ai_decision == "approve"
    assert not auto_approvable(reviewed, "approve", 0.94, [], min_occurrences=2)
    reviewed.flags = [flag for flag in reviewed.flags if flag != "asr_unscored"]
    assert auto_approvable(reviewed, "approve", 0.94, [], min_occurrences=2)
    assert not auto_approvable(reviewed, "approve", 0.94, ["omission"], min_occurrences=2)
    print("ok - AI 建议持久化与自动采纳门槛")

    assert db.approve_candidate(candidate_id, origin="human")
    assert db.candidate_count(status="pending") == 0
    tm_rows = db.list_tm(tgt_lang="zh", limit=10)
    assert len(tm_rows) == 1 and tm_rows[0].origin == "human"
    memory = TranslationMemory(db, "zh", min_quality=0.8)
    hit = memory.lookup(draft.src)
    assert hit is not None and hit.exact
    print("ok - 通过候选后进入正式语料并可命中")

    rejected_id = db.upsert_candidate(
        src="この機能はまだ実験段階ですので注意してください。",
        dst="这个功能还在实验阶段，请注意。",
        src_lang="ja",
        tgt_lang="zh",
        quality=0.7,
    )
    assert rejected_id
    db.reject_candidate(rejected_id, "人工拒绝")
    assert db.candidate_count(status="rejected") == 1
    db.restore_candidate(rejected_id)
    assert db.candidate_count(status="pending") == 1
    print("ok - 拒绝与恢复")

    low_id = db.upsert_candidate(
        src="低质量示例句子",
        dst="低质量示例译文",
        src_lang="ja",
        tgt_lang="zh",
        quality=0.5,
    )
    assert low_id
    db.approve_candidate(low_id, origin="auto", quality=0.5)
    memory.reload()
    assert memory.lookup("低质量示例句子") is None
    print("ok - 低质量条目不会参与检索")

    db.close()
    print("ALL CANDIDATE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
