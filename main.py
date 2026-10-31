"""RoseSI 启动入口（PyCharm 直接运行此文件）。"""

from __future__ import annotations

import multiprocessing
import sys

from app.application import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
