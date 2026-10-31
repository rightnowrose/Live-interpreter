"""浏览器标签页 WebSocket 接收测试（不依赖扩展）。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from websockets.sync.client import connect  # noqa: E402

from app.config import AudioSettings  # noqa: E402
from app.tab_capture import TabCapture  # noqa: E402

received = []
status = []

capture = TabCapture(
    AudioSettings(ws_port=17867),
    on_audio=lambda x: received.append(x.copy()),
    on_level=lambda x: None,
    on_error=lambda m: print("ERR", m),
    on_status=lambda m: (status.append(m), print("STATUS", m)),
)
capture.start()
time.sleep(0.6)
with connect("ws://127.0.0.1:17867/audio", open_timeout=5) as ws:
    ws.send('{"type":"hello","title":"测试标签页"}')
    ws.send(np.zeros(320, dtype="<f4").tobytes())
    ws.send((np.ones(320, dtype="<f4") * 0.2).tobytes())
    time.sleep(0.3)
print("received", len(received), [float(np.max(np.abs(x))) for x in received])
print("status", status)
capture.stop()
assert received, "没有收到音频"
assert abs(float(np.max(np.abs(received[-1]))) - 0.2) < 0.001
print("TAB TEST PASSED")
