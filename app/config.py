"""配置模型与持久化。"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from . import paths, secret

log = logging.getLogger(__name__)

CONFIG_VERSION = 5

LANGUAGES: dict[str, str] = {
    "auto": "自动检测",
    "zh": "简体中文",
    "zh-TW": "繁體中文",
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
    "fr": "法语",
    "de": "德语",
    "es": "西班牙语",
    "ru": "俄语",
    "pt": "葡萄牙语",
    "it": "意大利语",
    "ar": "阿拉伯语",
}

TARGET_LANGUAGES: dict[str, str] = {
    "zh": "简体中文",
    "zh-TW": "繁體中文",
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
    "fr": "法语",
    "de": "德语",
    "es": "西班牙语",
    "ru": "俄语",
}

STYLES: dict[str, str] = {
    "口语": "口语化、自然、适合即时字幕",
    "正式": "正式、完整、适合会议与演讲",
    "技术": "技术文档风格，术语精确、句式紧凑",
    "简洁": "极简，只保留核心信息",
}


def _filter(cls: type, data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    allowed = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in allowed}


@dataclass
class AudioSettings:
    source: str = "system"  # system | microphone | tab
    system_device: str = ""  # 输出设备 id；空=默认
    system_device_name: str = ""
    mic_id: str = ""  # 麦克风设备 id；空=默认
    mic_device: int = -1
    mic_name: str = ""
    process_pid: int = 0
    sample_rate: int = 48000
    gain: float = 1.0
    # 浏览器标签页扩展（可选）
    ws_port: int = 17866

    @classmethod
    def from_dict(cls, data: Any) -> "AudioSettings":
        return cls(**_filter(cls, data))


@dataclass
class ASRSettings:
    model: str = "parakeet-tdt-0.6b-ja"
    model_path: str = ""
    device: str = "auto"  # auto | cuda | cpu
    compute_type: str = "auto"  # auto | float16 | int8_float16 | int8 | float32
    language: str = "auto"
    beam_size: int = 5
    partial_beam_size: int = 1
    vad_threshold: float = 0.5
    silence_ms: int = 350
    silence_max_ms: int = 1200
    min_segment_ms: int = 400
    max_segment_ms: int = 8000
    partial_interval_ms: int = 700
    pre_roll_ms: int = 300
    initial_prompt: str = ""
    warmup: bool = True

    @classmethod
    def from_dict(cls, data: Any) -> "ASRSettings":
        return cls(**_filter(cls, data))


@dataclass
class TranslateSettings:
    provider: str = "deepseek"  # deepseek | local
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    thinking: bool = False
    api_key_enc: str = ""
    local_model: str = "hy-mt-1.8b-q4"
    local_model_path: str = ""
    local_gpu_layers: int = 99
    target_lang: str = "zh"
    temperature: float = 1.3
    max_tokens: int = 0
    context_sentences: int = 2
    timeout_s: float = 30.0
    max_pending: int = 2
    style: str = "口语"
    use_tm: bool = True
    auto_learn: bool = True
    auto_learn_mode: str = "candidates"  # off | candidates | auto
    auto_approve_quality: float = 0.85
    auto_approve_min_occurrences: int = 2
    auto_learn_min_chars: int = 6
    auto_learn_max_chars: int = 80
    candidate_max_per_session: int = 200
    candidate_reject_ttl_days: int = 30
    tm_fuzzy_min_quality: float = 0.8
    fuzzy_threshold: float = 0.93
    extra_prompt: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> "TranslateSettings":
        return cls(**_filter(cls, data))


@dataclass
class ReviewSettings:
    """AI 语料审核。默认关闭，只做建议，不直接改写人工语料。"""

    enabled: bool = False
    provider: str = "deepseek"  # deepseek（本地 Qwen 预留）
    model: str = "deepseek-flash"
    batch_size: int = 5
    auto_approve: bool = False
    min_auto_score: float = 0.9
    timeout_s: float = 60.0
    prompt_version: str = "v1"

    @classmethod
    def from_dict(cls, data: Any) -> "ReviewSettings":
        return cls(**_filter(cls, data))


@dataclass
class OverlaySettings:
    font_size: int = 22
    opacity: float = 0.82
    mode: str = "bilingual"  # focus | bilingual | study (legacy: both/dst/src)
    width: int = 900
    height: int = 0
    x: int = -1
    y: int = -1
    past_lines: int = 6
    click_through: bool = False
    always_on_top: bool = True
    show_toolbar: bool = True
    auto_hide_toolbar: bool = True
    show_latency: bool = True

    @classmethod
    def from_dict(cls, data: Any) -> "OverlaySettings":
        return cls(**_filter(cls, data))


@dataclass
class UISettings:
    first_run: bool = True
    last_page: str = "dashboard"
    active_bank_id: int = 0
    start_minimized: bool = False
    window_geometry: str = ""
    sidebar_collapsed: bool = False

    @classmethod
    def from_dict(cls, data: Any) -> "UISettings":
        return cls(**_filter(cls, data))


@dataclass
class HotkeySettings:
    toggle_start: str = "ctrl+shift+s"
    open_workbench: str = "ctrl+alt+w"
    toggle_click_through: str = "ctrl+alt+t"
    toggle_overlay: str = "ctrl+alt+h"
    open_kana: str = "ctrl+alt+k"

    @classmethod
    def from_dict(cls, data: Any) -> "HotkeySettings":
        return cls(**_filter(cls, data))


@dataclass
class AppSettings:
    version: int = CONFIG_VERSION
    audio: AudioSettings = field(default_factory=AudioSettings)
    asr: ASRSettings = field(default_factory=ASRSettings)
    translate: TranslateSettings = field(default_factory=TranslateSettings)
    review: ReviewSettings = field(default_factory=ReviewSettings)
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    ui: UISettings = field(default_factory=UISettings)
    hotkeys: HotkeySettings = field(default_factory=HotkeySettings)
    demo_mode: bool = False

    @classmethod
    def from_dict(cls, data: Any) -> "AppSettings":
        data = data if isinstance(data, dict) else {}
        return cls(
            version=int(data.get("version", CONFIG_VERSION) or CONFIG_VERSION),
            audio=AudioSettings.from_dict(data.get("audio")),
            asr=ASRSettings.from_dict(data.get("asr")),
            translate=TranslateSettings.from_dict(data.get("translate")),
            review=ReviewSettings.from_dict(data.get("review")),
            overlay=OverlaySettings.from_dict(data.get("overlay")),
            ui=UISettings.from_dict(data.get("ui")),
            hotkeys=HotkeySettings.from_dict(data.get("hotkeys")),
            demo_mode=bool(data.get("demo_mode", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConfigStore:
    """config.json 的读写与 API Key 加解密。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else paths.config_file()
        self.settings = AppSettings()
        self._api_key_cache: str | None = None
        self.load()

    def load(self) -> None:
        self._api_key_cache = None
        if not self.path.exists():
            self.settings = AppSettings()
            self.save()
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.settings = AppSettings.from_dict(raw)
            if self._migrate(raw):
                self.save()
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            log.warning("读取配置失败，使用默认配置: %s", exc)
            self.settings = AppSettings()

    def _migrate(self, raw: dict[str, Any]) -> bool:
        """配置迁移：旧版本默认 deepseek-chat -> 新版 deepseek-flash（关闭思考）。"""
        try:
            old_version = int(raw.get("version", 1) or 1)
        except (TypeError, ValueError):
            old_version = 1
        if old_version > CONFIG_VERSION:
            self.settings.version = old_version
            return False
        changed = old_version < CONFIG_VERSION
        if old_version < 2:
            model = (self.settings.translate.model or "").strip()
            if model in ("deepseek-chat", "deepseek-reasoner"):
                self.settings.translate.model = "deepseek-flash"
                self.settings.translate.thinking = False
                log.info("配置已迁移：%s -> deepseek-flash（关闭深度思考）", model)
        if old_version < 3 and int(self.settings.overlay.past_lines or 0) <= 1:
            self.settings.overlay.past_lines = 6
            log.info("配置已迁移：历史行数 1 -> 6")
        if old_version < 5:
            mode = getattr(self.settings.translate, "auto_learn_mode", "candidates")
            if mode not in ("off", "candidates", "auto"):
                mode = "candidates"
            if mode == "candidates" and not self.settings.translate.auto_learn:
                mode = "off"
            self.settings.translate.auto_learn_mode = mode
            log.info("配置已迁移：自动学习 -> %s", mode)
        legacy_modes = {"both": "bilingual", "dst": "focus", "src": "study"}
        if self.settings.overlay.mode in legacy_modes:
            self.settings.overlay.mode = legacy_modes[self.settings.overlay.mode]
            log.info("配置已迁移：字幕模式 -> %s", self.settings.overlay.mode)
            changed = True
        self.settings.version = CONFIG_VERSION
        return changed

    def save(self) -> None:
        payload = self.settings.to_dict()
        tmp = self.path.with_suffix(".json.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp, self.path)
        except OSError as exc:
            log.error("保存配置失败: %s", exc)

    # ----- API Key -----
    @property
    def api_key(self) -> str:
        if self._api_key_cache is None:
            self._api_key_cache = secret.decrypt(self.settings.translate.api_key_enc)
        return self._api_key_cache

    def set_api_key(self, key: str) -> None:
        key = (key or "").strip()
        self._api_key_cache = key
        self.settings.translate.api_key_enc = secret.encrypt(key)
        self.save()

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def reset(self) -> None:
        self.settings = AppSettings()
        self._api_key_cache = ""
        self.save()


def language_name(code: str) -> str:
    return LANGUAGES.get(code) or TARGET_LANGUAGES.get(code) or code


def target_language_name(code: str) -> str:
    return TARGET_LANGUAGES.get(code, code)


def whisper_language(code: str) -> str | None:
    if code in ("auto", "", None):
        return None
    if code == "zh-TW":
        return "zh"
    return code
