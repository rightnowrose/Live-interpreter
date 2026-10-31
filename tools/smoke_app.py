"""真实窗口启动冒烟测试：创建完整应用，截图后退出。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["SI_DATA_DIR"] = tempfile.mkdtemp(prefix="si_smoke_")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.application import InterpreterApp  # noqa: E402
from app.ui.theme import apply_theme  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)
    controller = InterpreterApp(app)
    out = ROOT / "docs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)

    def snap() -> None:
        controller.overlay.grab().save(str(out / "runtime_overlay.png"))
        if controller.workbench.isVisible():
            controller.workbench.grab().save(str(out / "runtime_workbench.png"))
        controller.overlay.show()
        controller.overlay.set_empty_text("等待声音…", "点击「开始」或按 Ctrl+Alt+S 启动同传")
        QTimer.singleShot(600, lambda: controller.overlay.grab().save(str(out / "runtime_overlay_idle.png")))
        QTimer.singleShot(1200, quit_app)

    def quit_app() -> None:
        controller.quit()

    QTimer.singleShot(1500, snap)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
