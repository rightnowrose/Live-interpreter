"""工作台 · 设置。"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QProgressDialog,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ... import audio, paths
from ...config import (
    LANGUAGES,
    STYLES,
    TARGET_LANGUAGES,
    ConfigStore,
)
from ..model_download import ModelDownloader
from ..parakeet_download import ParakeetDownloader
from ..widgets import Card, PageHeader, Switch, button
from .common import ask_confirm

if TYPE_CHECKING:
    from ...pipeline import Pipeline


class DeviceScan(QObject):
    done = Signal(list, list)

    def start(self) -> None:
        threading.Thread(target=self._run, name="device-scan", daemon=True).start()

    def _run(self) -> None:
        try:
            speakers = audio.list_speakers()
            microphones = audio.list_microphones()
        except Exception:
            speakers, microphones = [], []
        self.done.emit(speakers, microphones)


class SettingsPage(QWidget):
    notify = Signal(str, str)
    settings_saved = Signal()
    hotkeys_changed = Signal()
    preview_overlay = Signal()
    api_tested = Signal(bool, str)

    def __init__(
        self, pipeline: "Pipeline", config: ConfigStore, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.pipeline = pipeline
        self.config = config
        self._loading = False
        self._scanning = False
        self._pending_spk = ""
        self._pending_mic = ""
        self._scan = DeviceScan(self)
        self._scan.done.connect(self._apply_devices)
        self.api_tested.connect(self._on_api_tested)
        self._build()
        self.load()

    # ------------------------------------------------------------------ 构建
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 18)
        outer.setSpacing(14)
        header = PageHeader("设置", "所有配置保存在本机；API Key 使用 Windows DPAPI 加密")
        save_btn = button("保存并应用", "primary")
        save_btn.clicked.connect(self.save)
        reset_btn = button("恢复默认", "ghost")
        reset_btn.clicked.connect(self._reset)
        header.add_action(reset_btn)
        header.add_action(save_btn)
        outer.addWidget(header)

        self.banner = QLabel("")
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(
            "background: rgba(79,140,255,0.12); border: 1px solid rgba(79,140,255,0.3);"
            " color: #bcd3ff; border-radius: 8px; padding: 10px 14px; font-size: 12px;"
        )
        self.banner.setVisible(False)
        outer.addWidget(self.banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        self.form = QVBoxLayout(content)
        self.form.setContentsMargins(0, 0, 6, 12)
        self.form.setSpacing(16)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        self._build_translate()
        self._build_review()
        self._build_asr()
        self._build_audio()
        self._build_overlay()
        self._build_hotkeys()
        self._build_data()

    def _build_translate(self) -> None:
        card = Card("翻译服务")
        self.provider = QComboBox()
        self.provider.addItem("DeepSeek API（云端，质量优先）", "deepseek")
        self.provider.addItem("本地模型（离线，HY-MT1.5）", "local")
        self.provider.setMinimumWidth(300)
        self.provider_row = self._row(
            "翻译方式", self.provider, "本地模型不联网；首次使用需下载约 1.1 GB 模型"
        )
        card.add_widget(self.provider_row)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("sk-…")
        key_row = QWidget()
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(6)
        self.api_key.setMinimumWidth(300)
        key_layout.addWidget(self.api_key)
        show_btn = button("显示", "ghost")
        show_btn.setCheckable(True)
        show_btn.toggled.connect(
            lambda checked: self.api_key.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password
            )
        )
        key_layout.addWidget(show_btn)
        clear_btn = button("清除", "ghost")
        clear_btn.clicked.connect(lambda: self.api_key.setText(""))
        key_layout.addWidget(clear_btn)
        self.api_key_row = self._row("API Key", key_row, "加密保存在本机，不会写入日志")
        card.add_widget(self.api_key_row)

        self.base_url = QLineEdit()
        self.base_url.setMinimumWidth(360)
        self.base_url_row = self._row("Base URL", self.base_url, "OpenAI 兼容接口根地址")
        card.add_widget(self.base_url_row)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems(
            ["deepseek-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"]
        )
        self.model.setMinimumWidth(260)
        self.model_row = self._row(
            "云端模型", self.model, "实时字幕用 deepseek-flash；chat/reasoner 是旧名"
        )
        card.add_widget(self.model_row)
        self.thinking = Switch()
        self.thinking_row = self._row(
            "深度思考",
            self.thinking,
            "deepseek-flash 默认开启思考；实时字幕务必关闭，否则首包和费用都会增加",
        )
        card.add_widget(self.thinking_row)

        self.local_model = QComboBox()
        self.local_model.setMinimumWidth(320)
        for key, info in paths.LOCAL_MT_MODELS.items():
            size_gb = int(info.get("size") or 0) / (1024**3)
            self.local_model.addItem(f"{info['label']} · {size_gb:.1f} GB", key)
        self.local_model_row = self._row(
            "本地模型", self.local_model, "HY-MT1.5 专为翻译训练，支持日语/中文等 33+ 语言"
        )
        card.add_widget(self.local_model_row)

        self.local_path = QLineEdit()
        self.local_path.setMinimumWidth(320)
        self.local_path.setPlaceholderText("留空使用上面的内置模型；也可选择 .gguf 文件")
        local_path_row = QWidget()
        local_path_layout = QHBoxLayout(local_path_row)
        local_path_layout.setContentsMargins(0, 0, 0, 0)
        local_path_layout.setSpacing(6)
        local_path_layout.addWidget(self.local_path)
        local_browse = button("浏览", "ghost")
        local_browse.clicked.connect(self._browse_local_model)
        local_path_layout.addWidget(local_browse)
        self.local_path_row = self._row("模型文件", local_path_row)
        card.add_widget(self.local_path_row)

        self.local_gpu = QSpinBox()
        self.local_gpu.setRange(0, 99)
        self.local_gpu.setSuffix(" 层")
        self.local_gpu_row = self._row(
            "GPU 层数", self.local_gpu, "99=全部放到显卡；显存不足时调低，0=纯 CPU"
        )
        card.add_widget(self.local_gpu_row)

        local_status_row = QWidget()
        local_status_layout = QHBoxLayout(local_status_row)
        local_status_layout.setContentsMargins(0, 0, 0, 0)
        local_status_layout.setSpacing(8)
        self.local_status = QLabel("未下载")
        self.local_status.setObjectName("Dim")
        self.download_btn = button("下载模型", "soft")
        self.download_btn.clicked.connect(self._download_local_model)
        open_dir_btn = button("打开目录", "ghost")
        open_dir_btn.clicked.connect(self._open_local_dir)
        local_status_layout.addWidget(self.local_status)
        local_status_layout.addWidget(self.download_btn)
        local_status_layout.addWidget(open_dir_btn)
        self.local_status_row = self._row("模型状态", local_status_row)
        card.add_widget(self.local_status_row)

        self.target_lang = QComboBox()
        for code, name in TARGET_LANGUAGES.items():
            self.target_lang.addItem(name, code)
        card.add_widget(self._row("目标语言", self.target_lang))
        self.style = QComboBox()
        for name, desc in STYLES.items():
            self.style.addItem(f"{name} · {desc}", name)
        card.add_widget(self._row("翻译风格", self.style))
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.1)
        self.temperature.setDecimals(1)
        card.add_widget(self._row("温度", self.temperature, "1.3 适合翻译；越低越稳定"))
        self.context = QSpinBox()
        self.context.setRange(0, 6)
        card.add_widget(self._row("上下文句数", self.context, "注入最近几组原文/译文，帮助衔接"))
        self.extra_prompt = QLineEdit()
        self.extra_prompt.setMinimumWidth(380)
        card.add_widget(self._row("补充要求", self.extra_prompt, "可选，例如：保留英文缩写"))
        self.use_tm = Switch()
        card.add_widget(self._row("使用语料库", self.use_tm, "整句命中时跳过 API"))
        self.auto_learn_mode = QComboBox()
        self.auto_learn_mode.addItem("关闭", "off")
        self.auto_learn_mode.addItem("仅生成候选（推荐）", "candidates")
        self.auto_learn_mode.setMinimumWidth(220)
        card.add_widget(
            self._row(
                "自动学习",
                self.auto_learn_mode,
                "完成的译文先进入「语料库 → 待审核」；不会直接写入正式语料库",
            )
        )
        self.demo_mode = Switch()
        card.add_widget(
            self._row("演示模式", self.demo_mode, "不调用 API，只验证字幕与流程；正式使用请关闭")
        )
        test_row = QWidget()
        test_layout = QHBoxLayout(test_row)
        test_layout.setContentsMargins(0, 0, 0, 0)
        self.test_status = QLabel("未测试")
        self.test_status.setObjectName("Dim")
        self.test_btn = button("测试连接", "soft")
        self.test_btn.clicked.connect(self._test_api)
        test_layout.addWidget(self.test_btn)
        test_layout.addWidget(self.test_status)
        card.add_widget(self._row("连接测试", test_row))
        self.provider.currentIndexChanged.connect(self._sync_provider)
        self.local_model.currentIndexChanged.connect(self._on_local_model_changed)
        self.local_path.textChanged.connect(self._refresh_local_status)
        self._sync_provider()
        self.form.addWidget(card)

    def _build_review(self) -> None:
        card = Card("AI 语料审核")
        self.review_enabled = Switch()
        card.add_widget(
            self._row(
                "启用 AI 预审",
                self.review_enabled,
                "只审核「待审核」候选，给出建议，不会直接改写人工语料；默认关闭",
            )
        )
        self.review_model = QComboBox()
        self.review_model.setEditable(True)
        self.review_model.addItems(["deepseek-flash", "deepseek-v4-pro"])
        self.review_model.setMinimumWidth(260)
        card.add_widget(
            self._row(
                "审核模型",
                self.review_model,
                "使用上面的 DeepSeek API Key；建议 deepseek-flash，成本低、速度快",
            )
        )
        self.review_auto = Switch()
        card.add_widget(
            self._row(
                "自动采纳高置信建议",
                self.review_auto,
                "实验功能，默认关闭；仅在规则分≥0.85、AI 建议通过且无问题时自动写入正式语料库",
            )
        )
        self.review_status = QLabel("未启用")
        self.review_status.setObjectName("Dim")
        card.add_widget(self._row("审核状态", self.review_status, "AI 只处理候选；可随时关闭"))
        self.review_enabled.toggled.connect(self._refresh_review_status)
        self.review_auto.toggled.connect(self._refresh_review_status)
        if hasattr(self, "api_key"):
            self.api_key.textChanged.connect(lambda _: self._refresh_review_status())
        self.form.addWidget(card)

    def _refresh_review_status(self) -> None:
        if not hasattr(self, "review_status"):
            return
        if not self.review_enabled.isChecked():
            self.review_status.setText("未启用")
            self.review_status.setStyleSheet("color: #8b93a7;")
            return
        key = self.api_key.text().strip() if hasattr(self, "api_key") else self.config.api_key
        if not key:
            self.review_status.setText("需要 DeepSeek API Key")
            self.review_status.setStyleSheet("color: #f0a020;")
        else:
            self.review_status.setText("已启用 · 使用 DeepSeek 审核")
            self.review_status.setStyleSheet("color: #35c26b;")

    def _sync_provider(self) -> None:
        if not hasattr(self, "api_key_row"):
            return
        local = self.provider.currentData() == "local"
        # API Key 在本地翻译时仍可能要用于 AI 语料审核，因此保持可见。
        for row in (
            self.base_url_row,
            self.model_row,
            self.thinking_row,
        ):
            row.setVisible(not local)
        for row in (
            self.local_model_row,
            self.local_path_row,
            self.local_gpu_row,
            self.local_status_row,
        ):
            row.setVisible(local)
        self._refresh_local_status()

    def _refresh_local_status(self) -> None:
        if not hasattr(self, "local_status"):
            return
        key = self.local_model.currentData()
        if not key:
            self.local_status.setText("未选择模型")
            return
        path = paths.resolve_local_mt_model(key, self.local_path.text().strip())
        info = paths.local_mt_info(key)
        if path:
            size_mb = os.path.getsize(path) / (1024 * 1024)
            self.local_status.setText(f"已就绪 · {size_mb:.0f} MB")
            self.local_status.setStyleSheet("color: #35c26b;")
            self.local_status.setToolTip(path)
            self.download_btn.setEnabled(False)
            self.download_btn.setText("已下载")
        else:
            size_gb = int(info.get("size") or 0) / (1024**3)
            self.local_status.setText(f"未下载 · {size_gb:.1f} GB")
            self.local_status.setStyleSheet("color: #f0a020;")
            self.local_status.setToolTip(str(info.get("note") or "未下载"))
            self.download_btn.setEnabled(True)
            self.download_btn.setText("下载模型")

    def _on_local_model_changed(self) -> None:
        """切换内置模型时，清掉指向另一个内置模型的路径，避免路径覆盖选择。"""
        text = self.local_path.text().strip()
        if text:
            current = self.local_model.currentData()
            try:
                resolved = Path(text).resolve()
            except OSError:
                resolved = None
            for key in paths.LOCAL_MT_MODELS:
                expected = paths.local_mt_expected_path(key)
                try:
                    same = resolved is not None and expected.resolve() == resolved
                except OSError:
                    same = False
                if same and key != current:
                    self.local_path.clear()
                    break
        self._refresh_local_status()

    def _browse_local_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 GGUF 翻译模型", "", "GGUF 模型 (*.gguf);;所有文件 (*.*)"
        )
        if path:
            self.local_path.setText(path)
            self._refresh_local_status()

    def _open_local_dir(self) -> None:
        folder = paths.models_dir()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def _download_parakeet(self) -> None:
        missing = paths.parakeet_missing()
        if not missing:
            self.notify.emit("Parakeet 模型已经就绪", "info")
            self._refresh_asr_model_info()
            return
        size_gb = sum(paths.PARAKEET_FILES.values()) / (1024**3)
        if not ask_confirm(
            self,
            "下载 Parakeet 模型",
            f"需要下载约 {size_gb:.1f} GB 的 ONNX 模型文件，下载完成后即可离线识别。继续？",
        ):
            return
        self.parakeet_download_btn.setEnabled(False)
        dialog = QProgressDialog(
            f"正在下载 Parakeet TDT 0.6B JA（{size_gb:.1f} GB）…", "取消", 0, 1000, self
        )
        dialog.setWindowTitle("下载 Parakeet 模型")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        worker = ParakeetDownloader(self)
        self._parakeet_dialog = dialog
        self._parakeet_worker = worker
        worker.progress.connect(self._on_parakeet_progress)
        worker.finished.connect(self._on_parakeet_finished)
        worker.failed.connect(self._on_parakeet_failed)
        dialog.canceled.connect(worker.cancel)
        worker.start()

    def _on_parakeet_progress(self, done: int, total: int) -> None:
        dialog = getattr(self, "_parakeet_dialog", None)
        if dialog is None:
            return
        if total > 0:
            dialog.setMaximum(1000)
            dialog.setValue(max(0, min(1000, int(done * 1000 / total))))
            dialog.setLabelText(
                f"正在下载 Parakeet 模型…  {done / 1024 / 1024:.0f} / "
                f"{total / 1024 / 1024:.0f} MB"
            )

    def _on_parakeet_finished(self, folder: str) -> None:
        dialog = getattr(self, "_parakeet_dialog", None)
        if dialog is not None:
            dialog.close()
        self._parakeet_dialog = None
        self._parakeet_worker = None
        self._refresh_asr_model_info()
        self.notify.emit("Parakeet 模型下载完成，回到「实时同传」即可开始", "success")

    def _on_parakeet_failed(self, message: str) -> None:
        dialog = getattr(self, "_parakeet_dialog", None)
        if dialog is not None:
            dialog.close()
        self._parakeet_dialog = None
        self._parakeet_worker = None
        self._refresh_asr_model_info()
        self.notify.emit(f"Parakeet 模型下载失败：{message}", "error")

    def _download_local_model(self) -> None:
        key = self.local_model.currentData()
        if not key:
            return
        target = paths.local_mt_expected_path(key)
        if target.is_file():
            self.notify.emit("模型已经下载完成", "info")
            self._refresh_local_status()
            return
        info = paths.local_mt_info(key)
        size_gb = int(info.get("size") or 0) / (1024**3)
        if key == "hy-mt-7b-q4" and not ask_confirm(
            self,
            "下载 7B 模型",
            f"7B 模型约 {size_gb:.1f} GB，且 6 GB 显存可能需要调低 GPU 层数。继续下载？",
        ):
            return
        self.download_btn.setEnabled(False)
        dialog = QProgressDialog(
            f"正在下载 {info['label']}（{size_gb:.1f} GB）…", "取消", 0, 1000, self
        )
        dialog.setWindowTitle("下载本地翻译模型")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        worker = ModelDownloader(key, self)
        self._download_dialog = dialog
        self._downloader = worker
        worker.progress.connect(self._on_download_progress)
        worker.finished.connect(self._on_download_finished)
        worker.failed.connect(self._on_download_failed)
        dialog.canceled.connect(worker.cancel)
        worker.start()

    def _on_download_progress(self, done: int, total: int) -> None:
        dialog = getattr(self, "_download_dialog", None)
        if dialog is None:
            return
        if total > 0:
            dialog.setMaximum(1000)
            dialog.setValue(max(0, min(1000, int(done * 1000 / total))))
            dialog.setLabelText(
                f"正在下载本地翻译模型…  {done / 1024 / 1024:.0f} / "
                f"{total / 1024 / 1024:.0f} MB"
            )

    def _on_download_finished(self, path: str) -> None:
        dialog = getattr(self, "_download_dialog", None)
        if dialog is not None:
            dialog.close()
        self._download_dialog = None
        self._downloader = None
        self.local_path.setText(path)
        self._refresh_local_status()
        self.notify.emit("本地翻译模型下载完成，点击「保存并应用」后生效", "success")

    def _on_download_failed(self, message: str) -> None:
        dialog = getattr(self, "_download_dialog", None)
        if dialog is not None:
            dialog.close()
        self._download_dialog = None
        self._downloader = None
        self._refresh_local_status()
        self.notify.emit(f"模型下载失败：{message}", "error")

    def _build_asr(self) -> None:
        card = Card("本地识别 · Parakeet / faster-whisper")
        self.asr_model = QComboBox()
        self.asr_model.setMinimumWidth(300)
        for name in (
            "parakeet-tdt-0.6b-ja",
            "large-v3-turbo",
            "large-v3",
            "medium",
            "small",
            "tiny",
            "kotoba-whisper-v2.0-faster",
            "kotoba-whisper-bilingual-v1.0-faster",
        ):
            self.asr_model.addItem(name, name)
        card.add_widget(
            self._row(
                "模型",
                self.asr_model,
                "Parakeet TDT 0.6B JA 为直播首选，延迟更低；Whisper 作为备用/兼容选项",
            )
        )
        self.asr_model.currentIndexChanged.connect(self._refresh_asr_model_info)
        self.asr_model_info = QLabel()
        self.asr_model_info.setObjectName("Tiny")
        self.asr_model_info.setWordWrap(True)
        self.asr_model_info.setOpenExternalLinks(True)
        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        status_layout.addWidget(self.asr_model_info, 1)
        self.parakeet_download_btn = button("下载 Parakeet", "ghost")
        self.parakeet_download_btn.clicked.connect(self._download_parakeet)
        self.parakeet_download_btn.setVisible(False)
        status_layout.addWidget(self.parakeet_download_btn, 0, Qt.AlignTop)
        card.add_widget(self._row("模型状态", status_row))
        self.model_path = QLineEdit()
        self.model_path.setMinimumWidth(340)
        self.model_path.setPlaceholderText("留空自动查找 HuggingFace 缓存；也可填本地目录")
        self.model_path.textChanged.connect(self._refresh_asr_model_info)
        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(6)
        path_layout.addWidget(self.model_path)
        browse = button("浏览", "ghost")
        browse.clicked.connect(self._browse_model)
        path_layout.addWidget(browse)
        card.add_widget(self._row("模型路径", path_row))
        self.device = QComboBox()
        self.device.addItem("自动（优先 CUDA）", "auto")
        self.device.addItem("CUDA", "cuda")
        self.device.addItem("CPU", "cpu")
        card.add_widget(self._row("计算设备", self.device))
        self.compute = QComboBox()
        for text, value in (
            ("自动", "auto"),
            ("int8_float16（推荐）", "int8_float16"),
            ("float16", "float16"),
            ("int8", "int8"),
            ("float32", "float32"),
        ):
            self.compute.addItem(text, value)
        card.add_widget(self._row("量化精度", self.compute))
        self.asr_language = QComboBox()
        for code, name in LANGUAGES.items():
            self.asr_language.addItem(name, code)
        card.add_widget(self._row("源语言", self.asr_language, "固定语言通常比自动检测更稳"))
        self.beam = QSpinBox()
        self.beam.setRange(1, 8)
        card.add_widget(self._row("Beam size", self.beam, "越大越准，也越慢；实时建议 5"))
        self.vad = QDoubleSpinBox()
        self.vad.setRange(0.2, 0.9)
        self.vad.setSingleStep(0.05)
        card.add_widget(self._row("VAD 阈值", self.vad, "越高越不容易被噪声触发"))
        self.silence = QSpinBox()
        self.silence.setRange(150, 1200)
        self.silence.setSingleStep(50)
        self.silence.setSuffix(" ms")
        card.add_widget(self._row("静音断句", self.silence, "越小越快，但容易把句子切碎"))
        self.max_segment = QSpinBox()
        self.max_segment.setRange(3000, 20000)
        self.max_segment.setSingleStep(500)
        self.max_segment.setSuffix(" ms")
        card.add_widget(self._row("最大段长", self.max_segment, "防止长独白把延迟拉长"))
        self.partial_interval = QSpinBox()
        self.partial_interval.setRange(300, 1500)
        self.partial_interval.setSingleStep(100)
        self.partial_interval.setSuffix(" ms")
        card.add_widget(self._row("增量刷新", self.partial_interval, "说话过程中多久更新一次原文"))
        self.initial_prompt = QLineEdit()
        self.initial_prompt.setMinimumWidth(380)
        self.initial_prompt.setPlaceholderText("可选，例如：以下是关于 GPU 的技术演讲。")
        card.add_widget(self._row("识别提示", self.initial_prompt, "给 Whisper 的领域提示，可留空"))
        note = QLabel("修改模型 / 设备 / 量化后，需要停止并重新开始同传才会生效。")
        note.setObjectName("Tiny")
        note.setWordWrap(True)
        card.add_widget(note)
        self.form.addWidget(card)

    def _build_audio(self) -> None:
        card = Card("音频源")
        self.audio_source = QComboBox()
        self.audio_source.addItem("系统声音（含浏览器）", "system")
        self.audio_source.addItem("麦克风", "microphone")
        self.audio_source.addItem("浏览器标签页（扩展）", "tab")
        self.audio_source.currentIndexChanged.connect(self._sync_audio_controls)
        card.add_widget(self._row("来源", self.audio_source, "系统声音会捕获默认输出设备上的一切声音"))

        self.speaker_combo = QComboBox()
        self.speaker_combo.setMinimumWidth(380)
        speaker_row = QWidget()
        speaker_layout = QHBoxLayout(speaker_row)
        speaker_layout.setContentsMargins(0, 0, 0, 0)
        speaker_layout.setSpacing(6)
        speaker_layout.addWidget(self.speaker_combo)
        refresh_speaker = button("刷新", "ghost")
        refresh_speaker.clicked.connect(self._refresh_devices)
        speaker_layout.addWidget(refresh_speaker)
        self.speaker_row = self._row("输出设备", speaker_row, "选择浏览器实际播放声音的设备")
        card.add_widget(self.speaker_row)

        self.mic_combo = QComboBox()
        self.mic_combo.setMinimumWidth(380)
        mic_row = QWidget()
        mic_layout = QHBoxLayout(mic_row)
        mic_layout.setContentsMargins(0, 0, 0, 0)
        mic_layout.setSpacing(6)
        mic_layout.addWidget(self.mic_combo)
        refresh_mic = button("刷新", "ghost")
        refresh_mic.clicked.connect(self._refresh_devices)
        mic_layout.addWidget(refresh_mic)
        self.mic_row = self._row("麦克风", mic_row)
        card.add_widget(self.mic_row)

        self.gain = QSlider(Qt.Horizontal)
        self.gain.setRange(50, 200)
        self.gain.setFixedWidth(220)
        self.gain_label = QLabel("100%")
        self.gain_label.setObjectName("Dim")
        gain_row = QWidget()
        gain_layout = QHBoxLayout(gain_row)
        gain_layout.setContentsMargins(0, 0, 0, 0)
        gain_layout.addWidget(self.gain)
        gain_layout.addWidget(self.gain_label)
        self.gain.valueChanged.connect(lambda v: self.gain_label.setText(f"{v}%"))
        card.add_widget(self._row("输入增益", gain_row))

        self.tab_hint = QLabel("")
        self.tab_hint.setObjectName("Tiny")
        self.tab_hint.setWordWrap(True)
        self.tab_row = QWidget()
        tab_layout = QHBoxLayout(self.tab_row)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(8)
        tab_layout.addWidget(self.tab_hint, 1)
        open_ext = button("打开扩展文件夹", "soft")
        open_ext.clicked.connect(self._open_extension_dir)
        tab_layout.addWidget(open_ext)
        self.tab_row.setVisible(False)
        card.add_widget(self.tab_row)
        self.form.addWidget(card)

    def _build_overlay(self) -> None:
        card = Card("字幕窗")
        self.overlay_mode = QComboBox()
        self.overlay_mode.addItem("专注 · 只看当前译文", "focus")
        self.overlay_mode.addItem("双语 · 原文小、译文大", "bilingual")
        self.overlay_mode.addItem("学习 · 原文译文完整对照", "study")
        card.add_widget(self._row("显示模式", self.overlay_mode))
        self.font_size = QSpinBox()
        self.font_size.setRange(14, 40)
        self.font_size.setSuffix(" px")
        card.add_widget(self._row("字号", self.font_size))
        self.overlay_width = QSpinBox()
        self.overlay_width.setRange(520, 1900)
        self.overlay_width.setSingleStep(20)
        self.overlay_width.setSuffix(" px")
        card.add_widget(self._row("宽度", self.overlay_width))
        self.overlay_height = QSpinBox()
        self.overlay_height.setRange(0, 2200)
        self.overlay_height.setSingleStep(20)
        self.overlay_height.setSpecialValueText("自动")
        self.overlay_height.setSuffix(" px")
        card.add_widget(self._row("高度", self.overlay_height, "0 表示随内容自动；也可直接拖动字幕窗边缘"))
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(25, 100)
        self.opacity.setFixedWidth(220)
        self.opacity_label = QLabel("82%")
        self.opacity_label.setObjectName("Dim")
        opacity_row = QWidget()
        opacity_layout = QHBoxLayout(opacity_row)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_layout.addWidget(self.opacity)
        opacity_layout.addWidget(self.opacity_label)
        self.opacity.valueChanged.connect(lambda v: self.opacity_label.setText(f"{v}%"))
        card.add_widget(self._row("背景不透明度", opacity_row))
        self.past_lines = QSpinBox()
        self.past_lines.setRange(0, 12)
        card.add_widget(
            self._row(
                "历史行数",
                self.past_lines,
                "当前句之前保留几句；内容超出窗口高度时可用滚轮查看，0 表示只看当前",
            )
        )
        self.always_on_top = Switch()
        card.add_widget(self._row("窗口置顶", self.always_on_top))
        self.show_latency = Switch()
        card.add_widget(self._row("显示延迟", self.show_latency))
        self.click_through = Switch()
        card.add_widget(self._row("鼠标穿透", self.click_through, "开启后请用 Ctrl+Alt+T 关闭"))
        preview = button("预览 / 打开字幕窗", "soft")
        preview.clicked.connect(self.preview_overlay)
        card.add_widget(self._row("字幕窗", preview))
        self.form.addWidget(card)

    def _build_hotkeys(self) -> None:
        card = Card("全局热键")
        self.hk_start = QKeySequenceEdit()
        self.hk_workbench = QKeySequenceEdit()
        self.hk_kana = QKeySequenceEdit()
        self.hk_click = QKeySequenceEdit()
        self.hk_overlay = QKeySequenceEdit()
        card.add_widget(self._row("开始 / 停止", self.hk_start))
        card.add_widget(self._row("打开工作台", self.hk_workbench))
        card.add_widget(self._row("打开五十音图", self.hk_kana))
        card.add_widget(self._row("鼠标穿透", self.hk_click))
        card.add_widget(self._row("显示 / 隐藏字幕", self.hk_overlay))
        hint = QLabel("修改热键后保存即可生效；若被其他程序占用会提示失败。")
        hint.setObjectName("Tiny")
        card.add_widget(hint)
        self.form.addWidget(card)

    def _build_data(self) -> None:
        card = Card("数据与关于")
        data_label = QLabel(str(paths.data_dir()))
        data_label.setObjectName("Dim")
        data_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        open_data = button("打开数据目录", "soft")
        open_data.clicked.connect(lambda: os.startfile(paths.data_dir()))
        data_row = QWidget()
        data_layout = QHBoxLayout(data_row)
        data_layout.setContentsMargins(0, 0, 0, 0)
        data_layout.addWidget(data_label)
        data_layout.addWidget(open_data)
        card.add_widget(self._row("数据目录", data_row))
        open_exports = button("打开导出目录", "soft")
        open_exports.clicked.connect(lambda: os.startfile(paths.exports_dir()))
        card.add_widget(self._row("导出目录", open_exports))
        open_logs = button("查看日志", "ghost")
        open_logs.clicked.connect(lambda: os.startfile(paths.logs_dir() / "app.log"))
        card.add_widget(self._row("诊断日志", open_logs))
        author = QLabel("无媒介蔷薇")
        author.setObjectName("Dim")
        author.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.add_widget(self._row("作者", author))
        github = QLabel('<a href="https://github.com/rightnowrose">@rightnowrose</a>')
        github.setTextFormat(Qt.RichText)
        github.setOpenExternalLinks(True)
        github.setTextInteractionFlags(Qt.TextBrowserInteraction)
        card.add_widget(self._row("GitHub", github))
        bilibili = QLabel(
            '<a href="https://space.bilibili.com/3747570723589225/dynamic">'
            "space.bilibili.com/3747570723589225</a>"
        )
        bilibili.setTextFormat(Qt.RichText)
        bilibili.setOpenExternalLinks(True)
        bilibili.setTextInteractionFlags(Qt.TextBrowserInteraction)
        card.add_widget(self._row("Bilibili", bilibili))
        about = QLabel(
            "RoseSI · 本地实时同传\n"
            "ASR: Parakeet / faster-whisper（本地 GPU） · 翻译: DeepSeek / 本地 HY-MT\n"
            "术语匹配: Aho-Corasick 内存自动机 · 存储: SQLite"
        )
        about.setObjectName("Dim")
        about.setWordWrap(True)
        card.add_widget(about)
        self.form.addWidget(card)
        self.form.addStretch(1)

    # ------------------------------------------------------------------ 辅助
    def _row(self, label: str, control: QWidget, hint: str = "") -> QWidget:
        from ..widgets import FormRow

        return FormRow(label, control, hint)

    def _sync_audio_controls(self) -> None:
        source = self.audio_source.currentData()
        self.speaker_row.setVisible(source == "system")
        self.mic_row.setVisible(source == "microphone")
        self.tab_row.setVisible(source == "tab")
        if source == "tab":
            self.tab_hint.setText(
                "浏览器标签页模式需要安装随附的 Edge/Chrome 扩展：打开扩展管理页 → 开启开发者模式 →"
                " 加载解压缩的扩展 → 选择下方文件夹。安装后，在要翻译的标签页点击扩展图标即可开始/停止。"
            )

    def _refresh_devices(self) -> None:
        self._pending_spk = self.speaker_combo.currentData() or self.config.settings.audio.system_device
        self._pending_mic = self.mic_combo.currentData() or self.config.settings.audio.mic_id
        if self._scanning:
            return
        self._scanning = True
        self._scan.start()

    def _apply_devices(self, speakers: list, microphones: list) -> None:
        self._scanning = False
        self.speaker_combo.blockSignals(True)
        self.mic_combo.blockSignals(True)
        self.speaker_combo.clear()
        self.mic_combo.clear()
        self.speaker_combo.addItem("默认输出设备", "")
        for device in speakers:
            suffix = "（默认）" if device.is_default else ""
            self.speaker_combo.addItem(device.name + suffix, device.id)
        self.mic_combo.addItem("默认麦克风", "")
        for device in microphones:
            suffix = "（默认）" if device.is_default else ""
            self.mic_combo.addItem(device.name + suffix, device.id)
        for combo, value in (
            (self.speaker_combo, self._pending_spk),
            (self.mic_combo, self._pending_mic),
        ):
            index = combo.findData(value)
            combo.setCurrentIndex(index if index >= 0 else 0)
        self.speaker_combo.blockSignals(False)
        self.mic_combo.blockSignals(False)
        if not speakers and audio.available():
            self.notify.emit("没有枚举到输出设备，请检查系统音频设备", "warn")

    def _refresh_asr_model_info(self) -> None:
        name = self.asr_model.currentData() or "large-v3-turbo"
        is_parakeet = name == paths.PARAKEET_MODEL
        self.beam.setEnabled(not is_parakeet)
        self.compute.setEnabled(not is_parakeet)
        self.partial_interval.setEnabled(not is_parakeet)
        self.initial_prompt.setEnabled(not is_parakeet)
        hint = paths.asr_model_hint(name)
        url = paths.asr_model_url(name)
        self.parakeet_download_btn.setVisible(False)
        if is_parakeet:
            self.model_path.setPlaceholderText(
                "留空使用 data/models/parakeet-tdt-0.6b-ja；也可指定 ONNX 模型目录"
            )
            custom = bool(self.model_path.text().strip())
            folder = Path(self.model_path.text().strip()) if custom else paths.resolve_parakeet_dir()
            missing = [
                filename
                for filename, expected in paths.PARAKEET_FILES.items()
                if not (folder / filename).is_file()
                or (folder / filename).stat().st_size < int(expected * paths.PARAKEET_MIN_BYTES)
            ]
            if not missing:
                self.asr_model_info.setText(
                    f"<span style='color:#35c26b'>已就绪</span> · {folder}<br>{hint}"
                )
                self.parakeet_download_btn.setVisible(not custom)
                self.parakeet_download_btn.setEnabled(False)
                self.parakeet_download_btn.setText("已下载")
                return
            link = f"<a href='{url}'>打开下载页</a>" if url else "未收录下载地址"
            names = "、".join(missing[:2]) + (" 等" if len(missing) > 2 else "")
            self.asr_model_info.setText(
                f"<span style='color:#f0a020'>缺少 {len(missing)} 个文件</span>（{names}）· {link}<br>{hint}"
            )
            self.parakeet_download_btn.setVisible(not custom)
            self.parakeet_download_btn.setEnabled(True)
            self.parakeet_download_btn.setText("下载模型")
            return
        self.model_path.setPlaceholderText("留空自动查找 HuggingFace 缓存；也可填本地目录")
        resolved = self.model_path.text().strip() or paths.resolve_asr_model(name)
        path = Path(resolved)
        if path.is_dir() and (path / "model.bin").exists():
            try:
                builtin = path.resolve().is_relative_to(paths.bundled_models_dir().resolve())
            except (OSError, ValueError):
                builtin = False
            where = "安装包内置" if builtin else str(path)
            self.asr_model_info.setText(f"<span style='color:#35c26b'>已就绪</span> · {where}")
            return
        link = f"<a href='{url}'>打开下载页</a>" if url else "未收录下载地址"
        text = f"<span style='color:#f0a020'>未下载</span> · 首次使用会自动下载，也可 {link}"
        if hint:
            text += f"<br>{hint}"
        self.asr_model_info.setText(text)

    def _browse_model(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择模型目录")
        if path:
            self.model_path.setText(path)
            self._refresh_asr_model_info()

    def _open_extension_dir(self) -> None:
        folder = paths.extension_dir()
        if not (folder / "manifest.json").exists():
            self.notify.emit("没有找到扩展目录，请检查程序文件是否完整", "error")
            return
        os.startfile(str(folder))
        self.notify.emit(
            "已打开扩展目录。Edge/Chrome → 扩展管理 → 开启开发者模式 → 加载解压缩的扩展。",
            "info",
        )

    # ------------------------------------------------------------------ 载入/保存
    def load(self) -> None:
        self._loading = True
        s = self.config.settings
        self._select_data(self.provider, s.translate.provider)
        self._select_data(self.local_model, s.translate.local_model)
        self.local_path.setText(s.translate.local_model_path)
        self.local_gpu.setValue(int(s.translate.local_gpu_layers))
        self._sync_provider()
        self.api_key.setText(self.config.api_key)
        self.base_url.setText(s.translate.base_url)
        self.model.setCurrentText(s.translate.model)
        self.thinking.setChecked(s.translate.thinking)
        self._select_data(self.target_lang, s.translate.target_lang)
        self._select_data(self.style, s.translate.style)
        self.temperature.setValue(float(s.translate.temperature))
        self.context.setValue(int(s.translate.context_sentences))
        self.extra_prompt.setText(s.translate.extra_prompt)
        self.use_tm.setChecked(s.translate.use_tm)
        mode = getattr(s.translate, "auto_learn_mode", "candidates")
        mode_index = self.auto_learn_mode.findData(mode)
        self.auto_learn_mode.setCurrentIndex(mode_index if mode_index >= 0 else 1)
        self.review_enabled.setChecked(bool(s.review.enabled))
        self.review_model.setCurrentText(s.review.model or "deepseek-flash")
        self.review_auto.setChecked(bool(s.review.auto_approve))
        self._refresh_review_status()
        self.demo_mode.setChecked(s.demo_mode)

        self.asr_model.setCurrentIndex(max(0, self.asr_model.findData(s.asr.model)))
        self.model_path.setText(s.asr.model_path)
        self._select_data(self.device, s.asr.device)
        self._select_data(self.compute, s.asr.compute_type)
        self._select_data(self.asr_language, s.asr.language)
        self.beam.setValue(int(s.asr.beam_size))
        self.vad.setValue(float(s.asr.vad_threshold))
        self.silence.setValue(int(s.asr.silence_ms))
        self.max_segment.setValue(int(s.asr.max_segment_ms))
        self.partial_interval.setValue(int(s.asr.partial_interval_ms))
        self.initial_prompt.setText(s.asr.initial_prompt)
        self._refresh_asr_model_info()

        self._select_data(self.audio_source, s.audio.source)
        self._pending_spk = s.audio.system_device
        self._pending_mic = s.audio.mic_id
        self._refresh_devices()
        self._select_data(self.speaker_combo, s.audio.system_device)
        self._select_data(self.mic_combo, s.audio.mic_id)
        self.gain.setValue(int(round(s.audio.gain * 100)))
        self._sync_audio_controls()

        self._select_data(self.overlay_mode, s.overlay.mode)
        self.font_size.setValue(int(s.overlay.font_size))
        self.overlay_width.setValue(int(s.overlay.width))
        self.overlay_height.setValue(int(s.overlay.height))
        self.opacity.setValue(int(round(s.overlay.opacity * 100)))
        self.past_lines.setValue(int(s.overlay.past_lines))
        self.always_on_top.setChecked(s.overlay.always_on_top)
        self.show_latency.setChecked(s.overlay.show_latency)
        self.click_through.setChecked(s.overlay.click_through)

        self.hk_start.setKeySequence(QKeySequence(s.hotkeys.toggle_start))
        self.hk_workbench.setKeySequence(QKeySequence(s.hotkeys.open_workbench))
        self.hk_kana.setKeySequence(QKeySequence(s.hotkeys.open_kana))
        self.hk_click.setKeySequence(QKeySequence(s.hotkeys.toggle_click_through))
        self.hk_overlay.setKeySequence(QKeySequence(s.hotkeys.toggle_overlay))

        self.banner.setVisible(s.ui.first_run)
        if s.ui.first_run:
            self.banner.setText(
                "欢迎使用 RoseSI。选择「DeepSeek API」或「本地模型」，"
                "确认音频源，然后点击右上角「保存并应用」。字幕窗常驻桌面，"
                "随时可以点「工作台」回到这里。"
            )
        self._loading = False

    def sync_overlay(self) -> None:
        """字幕窗被拖动/改字号后，只同步字幕相关控件，不打断其他正在编辑的字段。"""
        s = self.config.settings.overlay
        self._select_data(self.overlay_mode, s.mode)
        self.font_size.setValue(int(s.font_size))
        self.overlay_width.setValue(int(s.width))
        self.overlay_height.setValue(int(s.height))
        self.opacity.setValue(int(round(s.opacity * 100)))
        self.past_lines.setValue(int(s.past_lines))
        self.always_on_top.setChecked(s.always_on_top)
        self.show_latency.setChecked(s.show_latency)
        self.click_through.setChecked(s.click_through)

    @staticmethod
    def _select_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def save(self) -> None:
        if self._loading:
            return
        s = self.config.settings
        key = self.api_key.text().strip()
        if key != self.config.api_key:
            self.config.set_api_key(key)

        s.translate.provider = self.provider.currentData() or "deepseek"
        s.translate.local_model = self.local_model.currentData() or paths.DEFAULT_LOCAL_MT
        s.translate.local_model_path = self.local_path.text().strip()
        s.translate.local_gpu_layers = int(self.local_gpu.value())
        s.translate.base_url = self.base_url.text().strip() or "https://api.deepseek.com"
        s.translate.model = self.model.currentText().strip() or "deepseek-flash"
        s.translate.thinking = self.thinking.isChecked()
        s.translate.target_lang = self.target_lang.currentData()
        s.translate.style = self.style.currentData()
        s.translate.temperature = float(self.temperature.value())
        s.translate.context_sentences = int(self.context.value())
        s.translate.extra_prompt = self.extra_prompt.text().strip()
        s.translate.use_tm = self.use_tm.isChecked()
        s.translate.auto_learn_mode = self.auto_learn_mode.currentData() or "candidates"
        s.translate.auto_learn = s.translate.auto_learn_mode != "off"
        s.review.enabled = self.review_enabled.isChecked()
        s.review.model = self.review_model.currentText().strip() or "deepseek-flash"
        s.review.auto_approve = self.review_auto.isChecked()
        s.demo_mode = self.demo_mode.isChecked()

        s.asr.model = self.asr_model.currentData() or "large-v3-turbo"
        s.asr.model_path = self.model_path.text().strip()
        if s.asr.model == paths.PARAKEET_MODEL:
            folder = Path(s.asr.model_path) if s.asr.model_path else paths.resolve_parakeet_dir()
            missing = [
                filename
                for filename, expected in paths.PARAKEET_FILES.items()
                if not (folder / filename).is_file()
                or (folder / filename).stat().st_size < int(expected * paths.PARAKEET_MIN_BYTES)
            ]
            if missing:
                self.notify.emit(
                    "Parakeet 模型不完整：缺少 "
                    + "、".join(missing[:3])
                    + "。请重新下载模型，或在「模型路径」中指定完整目录。",
                    "error",
                )
                return
        if s.asr.model.startswith("kotoba-whisper"):
            resolved = s.asr.model_path or paths.resolve_asr_model(s.asr.model)
            if not os.path.isdir(resolved):
                self.notify.emit(
                    "该 Kotoba 模型尚未下载到本地：请把模型目录放到 data/models 下，"
                    "或在「模型路径」中指定目录。",
                    "error",
                )
                return
        s.asr.device = self.device.currentData()
        s.asr.compute_type = self.compute.currentData()
        s.asr.language = self.asr_language.currentData()
        s.asr.beam_size = int(self.beam.value())
        s.asr.vad_threshold = float(self.vad.value())
        s.asr.silence_ms = int(self.silence.value())
        s.asr.max_segment_ms = int(self.max_segment.value())
        s.asr.partial_interval_ms = int(self.partial_interval.value())
        s.asr.initial_prompt = self.initial_prompt.text().strip()

        s.audio.source = self.audio_source.currentData()
        s.audio.system_device = self.speaker_combo.currentData() or ""
        s.audio.system_device_name = (
            self.speaker_combo.currentText().replace("（默认）", "").strip()
            if self.speaker_combo.currentData()
            else "默认输出设备"
        )
        s.audio.mic_id = self.mic_combo.currentData() or ""
        s.audio.mic_name = (
            self.mic_combo.currentText().replace("（默认）", "").strip()
            if self.mic_combo.currentData()
            else "默认麦克风"
        )
        s.audio.gain = round(self.gain.value() / 100.0, 2)

        s.overlay.mode = self.overlay_mode.currentData()
        s.overlay.font_size = int(self.font_size.value())
        s.overlay.width = int(self.overlay_width.value())
        s.overlay.height = int(self.overlay_height.value())
        s.overlay.opacity = round(self.opacity.value() / 100.0, 2)
        s.overlay.past_lines = int(self.past_lines.value())
        s.overlay.always_on_top = self.always_on_top.isChecked()
        s.overlay.show_latency = self.show_latency.isChecked()
        s.overlay.click_through = self.click_through.isChecked()

        s.hotkeys.toggle_start = self.hk_start.keySequence().toString()
        s.hotkeys.open_workbench = self.hk_workbench.keySequence().toString()
        s.hotkeys.open_kana = self.hk_kana.keySequence().toString()
        s.hotkeys.toggle_click_through = self.hk_click.keySequence().toString()
        s.hotkeys.toggle_overlay = self.hk_overlay.keySequence().toString()
        s.ui.first_run = False
        self.config.save()

        self.pipeline.apply_settings()
        self.settings_saved.emit()
        self.hotkeys_changed.emit()
        self.banner.setVisible(False)
        self.notify.emit("设置已保存并应用", "success")

    def _reset(self) -> None:
        if not ask_confirm(self, "恢复默认", "确定恢复所有设置为默认值？API Key 也会被清除。"):
            return
        self.config.reset()
        self.load()
        self.pipeline.apply_settings()
        self.settings_saved.emit()
        self.hotkeys_changed.emit()
        self.notify.emit("已恢复默认设置", "success")

    def _test_api(self) -> None:
        self.test_btn.setEnabled(False)
        self.test_status.setText("测试中…")
        self.test_status.setStyleSheet("color: #f0a020;")
        self.save()

        def work() -> None:
            try:
                ok, message = self.pipeline._translator.test_connection()
            except Exception as exc:
                ok, message = False, str(exc)
            self.api_tested.emit(ok, message)

        threading.Thread(target=work, daemon=True).start()

    def _on_api_tested(self, ok: bool, message: str) -> None:
        self.test_btn.setEnabled(True)
        local = self.provider.currentData() == "local"
        if ok:
            self.test_status.setText("本地可用" if local else "连接正常")
        else:
            self.test_status.setText("本地不可用" if local else "连接失败")
        self.test_status.setStyleSheet("color: #35c26b;" if ok else "color: #e5484d;")
        self.test_status.setToolTip(message)
        self.notify.emit(message, "success" if ok else "error")
