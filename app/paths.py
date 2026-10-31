"""应用路径、日志与本地模型发现。"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_DIR_NAME = "LocalInterpreter"  # 兼容旧配置/模型目录；品牌名为 RoseSI

# faster-whisper 官方 / 社区转换仓库
MODEL_REPOS: dict[str, tuple[str, str]] = {
    "parakeet-tdt-0.6b-ja": ("visuall", "parakeet-tdt_ctc-0.6b-ja-onnx"),
    "large-v3-turbo": ("mobiuslabsgmbh", "faster-whisper-large-v3-turbo"),
    "large-v3": ("Systran", "faster-whisper-large-v3"),
    "medium": ("Systran", "faster-whisper-medium"),
    "small": ("Systran", "faster-whisper-small"),
    "base": ("Systran", "faster-whisper-base"),
    "tiny": ("Systran", "faster-whisper-tiny"),
    "kotoba-whisper-v2.0-faster": ("kotoba-tech", "kotoba-whisper-v2.0-faster"),
    "kotoba-whisper-bilingual-v1.0-faster": (
        "kotoba-tech",
        "kotoba-whisper-bilingual-v1.0-faster",
    ),
}

PARAKEET_MODEL = "parakeet-tdt-0.6b-ja"
PARAKEET_FILES: dict[str, int] = {
    "encoder-model.fp16.onnx": 1237097381,
    "decoder_joint-model.fp16.onnx": 23152215,
    "nemo80.onnx": 90418,
    "vocab.txt": 28557,
}
PARAKEET_MIN_BYTES = 0.98

# 本地翻译（GGUF）模型。label 用于界面，filename 必须与下载文件一致。
LOCAL_MT_MODELS: dict[str, dict[str, object]] = {
    "hy-mt-1.8b-q4": {
        "label": "HY-MT1.5 1.8B · Q4_K_M",
        "short": "HY-MT1.5-1.8B",
        "repo": "tencent/HY-MT1.5-1.8B-GGUF",
        "folder": "HY-MT1.5-1.8B-GGUF",
        "filename": "HY-MT1.5-1.8B-Q4_K_M.gguf",
        "size": 1133080512,
        "recommended": True,
        "note": "推荐：约 1.1 GB，6 GB 显存可全量 GPU，速度与质量平衡",
    },
    "hy-mt-7b-q4": {
        "label": "HY-MT1.5 7B · Q4_K_M",
        "short": "HY-MT1.5-7B",
        "repo": "tencent/HY-MT1.5-7B-GGUF",
        "folder": "HY-MT1.5-7B-GGUF",
        "filename": "HY-MT1.5-7B-Q4_K_M.gguf",
        "size": 4620000000,
        "recommended": False,
        "note": "质量优先：约 4.6 GB，6 GB 显存需要部分卸载或调低 GPU 层数",
    },
}

DEFAULT_LOCAL_MT = "hy-mt-1.8b-q4"


def bundle_root() -> Path:
    """打包后的程序根目录；源码运行时是项目根目录。"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def bundled_models_dir() -> Path:
    """安装包内自带的只读模型目录。

    onedir 优先使用 exe 同级的 models/（方便用户查看），onefile 使用
    PyInstaller 解压目录中的 models/。`SI_BUNDLED_MODELS` 可覆盖。
    """
    override = os.environ.get("SI_BUNDLED_MODELS")
    if override:
        return Path(override).expanduser()
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "models")
    candidates.append(bundle_root() / "models")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def asr_model_url(name: str) -> str:
    """faster-whisper 模型的浏览/下载页（默认走 hf-mirror）。"""
    repo = MODEL_REPOS.get(name)
    if not repo:
        return ""
    endpoint = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")
    return f"{endpoint}/{repo[0]}/{repo[1]}/tree/main"


def asr_model_hint(name: str) -> str:
    if name == PARAKEET_MODEL:
        return "直播首选：日语句级识别 + 低延迟；发行版内置，可直接使用"
    if name.startswith("kotoba-whisper"):
        return "日语/中日双语优化模型，需完整模型目录"
    if name == "large-v3-turbo":
        return "速度快、精度高；发行版未内置，可在模型入口直接下载"
    if name == "large-v3":
        return "精度最高，但显存和速度开销更大"
    if name in ("medium", "small", "base", "tiny"):
        return "更小更快，适合 CPU 或低显存"
    return ""


def data_dir() -> Path:
    """可写数据目录。设置 SI_DATA_DIR 可做便携模式。"""
    override = os.environ.get("SI_DATA_DIR")
    if override:
        path = Path(override).expanduser()
    else:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        path = Path(base) / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    return data_dir() / "config.json"


def db_file() -> Path:
    return data_dir() / "interpreter.db"


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def exports_dir() -> Path:
    path = data_dir() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def parakeet_dir() -> Path:
    """用户可写模型目录（下载/自定义安装）。"""
    return models_dir() / PARAKEET_MODEL


def bundled_parakeet_dir() -> Path:
    """安装包内置的只读 Parakeet 目录。"""
    return bundled_models_dir() / PARAKEET_MODEL


def _parakeet_folder_ready(folder: Path) -> bool:
    for name, expected in PARAKEET_FILES.items():
        file = folder / name
        if not file.is_file() or file.stat().st_size < int(expected * PARAKEET_MIN_BYTES):
            return False
    return True


def resolve_parakeet_dir() -> Path:
    """优先用户目录，其次安装包内置目录。"""
    local = parakeet_dir()
    if _parakeet_folder_ready(local):
        return local
    bundled = bundled_parakeet_dir()
    if _parakeet_folder_ready(bundled):
        return bundled
    return local


def parakeet_ready() -> bool:
    return _parakeet_folder_ready(resolve_parakeet_dir())


def parakeet_missing() -> list[str]:
    folder = resolve_parakeet_dir()
    return [
        name
        for name, expected in PARAKEET_FILES.items()
        if not (folder / name).is_file()
        or (folder / name).stat().st_size < int(expected * PARAKEET_MIN_BYTES)
    ]


def parakeet_download_url(filename: str) -> str:
    """Parakeet ONNX 文件下载地址（默认走 hf-mirror）。"""
    owner, repo = MODEL_REPOS[PARAKEET_MODEL]
    endpoint = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")
    return f"{endpoint}/{owner}/{repo}/resolve/main/{filename}"


def extension_dir() -> Path:
    """浏览器扩展目录（源码运行 / PyInstaller 打包都尽量找到）。"""
    candidates = [
        Path(__file__).resolve().parents[1] / "extension",
        Path.cwd() / "extension",
        Path(sys.executable).resolve().parent / "extension",
        Path(getattr(sys, "_MEIPASS", "")) / "extension",
    ]
    for candidate in candidates:
        if (candidate / "manifest.json").exists():
            return candidate
    return candidates[0]


def hf_cache_dir() -> Path:
    env = os.environ.get("HUGGINGFACE_HUB_CACHE")
    if env:
        return Path(env).expanduser()
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home).expanduser() / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _newest_snapshot(repo_dir: Path) -> Path | None:
    snapshots = repo_dir / "snapshots"
    if not snapshots.is_dir():
        return None
    candidates: list[Path] = []
    for path in snapshots.iterdir():
        model_bin = path / "model.bin"
        try:
            if model_bin.exists() and model_bin.stat().st_size > 50 * 1024 * 1024:
                candidates.append(path)
        except OSError:
            continue
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def resolve_asr_model(name_or_path: str) -> str:
    """把模型名解析成可直接加载的目录；找不到时原样返回让 faster-whisper 自行下载。"""
    if not name_or_path:
        return "large-v3-turbo"
    candidate = Path(name_or_path).expanduser()
    if candidate.exists():
        return str(candidate)

    local = models_dir() / name_or_path
    if (local / "model.bin").exists():
        return str(local)

    bundled = bundled_models_dir() / name_or_path
    if (bundled / "model.bin").exists():
        return str(bundled)

    repo = MODEL_REPOS.get(name_or_path)
    if not repo:
        return name_or_path

    org, repo_name = repo
    snapshot = _newest_snapshot(hf_cache_dir() / f"models--{org}--{repo_name}")
    if snapshot:
        return str(snapshot)
    # 让 faster-whisper / huggingface_hub 用正确的仓库 ID 下载（例如 turbo 不是 Systran 仓库）
    return f"{org}/{repo_name}"


def installed_models() -> list[tuple[str, str, bool]]:
    """返回 (模型名, 解析后的路径, 是否已下载)。"""
    result: list[tuple[str, str, bool]] = []
    for name in MODEL_REPOS:
        resolved = resolve_asr_model(name)
        result.append((name, resolved, Path(resolved).is_dir()))
    return result


def local_mt_info(key: str) -> dict[str, object]:
    return LOCAL_MT_MODELS.get(key) or LOCAL_MT_MODELS[DEFAULT_LOCAL_MT]


def local_mt_expected_path(key: str) -> Path:
    info = local_mt_info(key)
    return models_dir() / str(info["folder"]) / str(info["filename"])


def local_mt_label(key: str) -> str:
    return str(local_mt_info(key).get("short") or key)


def local_mt_file_ready(key: str, path: str) -> bool:
    """已知模型要求文件完整；下载中断留下的半文件不能交给 llama.cpp。"""
    try:
        size = Path(path).stat().st_size
    except OSError:
        return False
    info = LOCAL_MT_MODELS.get(key)
    expected = int(info.get("size") or 0) if info else 0
    if expected:
        return size >= expected * 0.98
    return size > 1024 * 1024


def resolve_local_mt_model(key: str, custom_path: str = "") -> str:
    """解析本地翻译模型文件；找不到返回空字符串，避免把坏路径交给 llama.cpp。"""
    custom = (custom_path or "").strip()
    if custom:
        candidate = Path(custom).expanduser()
        return str(candidate) if candidate.is_file() else ""

    value = (key or "").strip()
    if not value:
        value = DEFAULT_LOCAL_MT
    direct = Path(value).expanduser()
    if direct.is_file():
        return str(direct)
    if direct.suffix.lower() == ".gguf":
        return ""

    info = LOCAL_MT_MODELS.get(value)
    if info:
        candidates = [
            local_mt_expected_path(value),
            models_dir() / str(info["filename"]),
            bundled_models_dir() / str(info["folder"]) / str(info["filename"]),
            bundled_models_dir() / str(info["filename"]),
        ]
        for path in candidates:
            if path.is_file() and local_mt_file_ready(value, str(path)):
                return str(path)
        try:
            for root in (models_dir(), bundled_models_dir()):
                for path in root.glob(f"*/{info['filename']}"):
                    if path.is_file() and local_mt_file_ready(value, str(path)):
                        return str(path)
        except OSError:
            pass
        return ""

    # 用户可能直接把路径填进了“模型”字段。
    candidate = models_dir() / value
    return str(candidate) if candidate.is_file() else ""


def local_mt_download_url(key: str) -> str:
    info = local_mt_info(key)
    repo = str(info["repo"])
    filename = str(info["filename"])
    endpoint = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")
    return f"{endpoint}/{repo}/resolve/main/{filename}"


def installed_local_mt_models() -> list[tuple[str, str, bool]]:
    result: list[tuple[str, str, bool]] = []
    for key in LOCAL_MT_MODELS:
        resolved = resolve_local_mt_model(key)
        result.append((key, resolved, Path(resolved).is_file()))
    return result


def is_windows() -> bool:
    return sys.platform == "win32"


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if getattr(root, "_si_configured", False):
        return
    root.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"
    )
    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)

    try:
        file_handler = RotatingFileHandler(
            logs_dir() / "app.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        pass
    root._si_configured = True  # type: ignore[attr-defined]
