"""翻译链路自检：本地伪 SSE 服务 + 语料库 + 演示模式。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["SI_DATA_DIR"] = tempfile.mkdtemp(prefix="si_translate_")

from app.config import TranslateSettings  # noqa: E402
from app.db import Database  # noqa: E402
from app.tm import TranslationMemory  # noqa: E402
from app.translator import (  # noqa: E402
    DeepSeekClient,
    TranslationService,
    iter_sse,
)


class Handler(BaseHTTPRequestHandler):
    captured = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        self.captured.append(payload)
        if self.path.startswith("/fail"):
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"invalid key"}}')
            return
        if not payload.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"choices": [{"message": {"content": "ok"}}], "usage": {}}
                ).encode()
            )
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for piece in ("延迟", "主要由", " VAD ", "决定。"):
            chunk = {"choices": [{"delta": {"content": piece}}]}
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.01)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("ok -", message)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"

    settings = TranslateSettings(
        base_url=base, model="mock", api_key_enc="", target_lang="zh"
    )
    client = DeepSeekClient(settings, "test-key")
    deltas = []
    text, ttfb, total = client.translate_stream(
        [{"role": "user", "content": "hi"}], 64, on_delta=deltas.append
    )
    check(text == "延迟主要由 VAD 决定。", "SSE 拼接")
    check(len(deltas) == 4 and ttfb > 0 and total >= ttfb, "TTFB / 流式回调")
    ok, message = client.test_connection()
    check(ok, "连接测试")
    client.close()

    bad = DeepSeekClient(
        TranslateSettings(base_url=base + "/fail", model="mock"), "bad"
    )
    try:
        bad.translate_stream([{"role": "user", "content": "hi"}], 64)
        raise AssertionError("应当失败")
    except Exception as exc:
        check("invalid key" in str(exc), "错误信息透传")
    bad.close()

    flash = DeepSeekClient(
        TranslateSettings(base_url=base, model="deepseek-flash", thinking=False),
        "test-key",
    )
    flash.translate_stream([{"role": "user", "content": "hi"}], 64)
    check(
        Handler.captured[-1].get("thinking") == {"type": "disabled"},
        "deepseek-flash 默认关闭 thinking",
    )
    flash.close()

    events = list(iter_sse(['data: {"choices":[]}', "", "data: [DONE]"]))
    check(events == [{"choices": []}], "SSE 解析")

    db = Database()
    db.upsert_tm("The latency is mainly determined by VAD.", "延迟主要由 VAD 决定。", tgt_lang="zh")
    memory = TranslationMemory(db, "zh")
    service = TranslationService(
        TranslateSettings(base_url=base, model="mock", target_lang="zh"), "test-key", memory
    )
    result = service.translate(
        "The latency is mainly determined by VAD.", [], [], "en"
    )
    check(result.via_tm and result.text == "延迟主要由 VAD 决定。", "语料库零延迟命中")
    service.close()
    db.close()
    server.shutdown()
    print("\nALL TRANSLATE TESTS PASSED")


if __name__ == "__main__":
    main()
