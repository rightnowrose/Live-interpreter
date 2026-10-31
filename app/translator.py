"""流式翻译：DeepSeek（OpenAI 兼容）或本地 HY-MT1.5 GGUF。"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator

import httpx

from . import paths
from .config import (
    STYLES,
    TranslateSettings,
    language_name,
    target_language_name,
)
from .glossary import TermHit, missing_terms, render_glossary

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是一名资深同声传译员，正在为实时字幕做{src}到{tgt}的翻译。\n"
    "规则：\n"
    "1. 只输出{tgt}译文，不要输出原文、解释、注音、标签、引号或 Markdown。\n"
    "2. 译文简洁、自然、{style}，适合逐句阅读；不增删信息，不扩写。\n"
    "3. 数字、人名、产品名、缩写必须准确。\n"
    "4. 如果给出【术语表】，必须使用表中译法，不得改写。\n"
    "5. 只翻译【待翻译】部分，不要重复上文。"
)


class TranslationError(RuntimeError):
    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class TranslationCancelled(TranslationError):
    def __init__(self) -> None:
        super().__init__("翻译已取消", retryable=False)


@dataclass
class TranslationResult:
    text: str
    ttfb_ms: float
    total_ms: float
    model: str
    via_tm: bool = False
    tm_score: float = 0.0
    missing_terms: list[str] = field(default_factory=list)


Callback = Callable[[str], None]


def build_messages(
    text: str,
    hits: list[TermHit],
    context: list[tuple[str, str]],
    settings: TranslateSettings,
    reference: str = "",
    source_lang: str = "auto",
) -> list[dict[str, str]]:
    target = target_language_name(settings.target_lang)
    source = language_name(source_lang) if source_lang != "auto" else "源语言"
    style = STYLES.get(settings.style, settings.style)
    system = SYSTEM_PROMPT.format(src=source, tgt=target, style=style)

    extra = (settings.extra_prompt or "").strip()
    if extra:
        system += f"\n补充要求：{extra}"

    glossary = render_glossary(hits)
    if glossary:
        system += "\n\n【术语表】（必须遵守）\n" + glossary

    if reference:
        system += "\n\n【参考译文】（来自本地语料库，可润色，不要照抄错误）\n" + reference

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    context_limit = max(0, int(settings.context_sentences))
    if context_limit:
        for src, dst in context[-context_limit:]:
            messages.append({"role": "user", "content": f"【上文原文】\n{src}"})
            messages.append({"role": "assistant", "content": dst})
    messages.append({"role": "user", "content": f"【待翻译】\n{text}"})
    return messages


def estimate_max_tokens(text: str, target_lang: str) -> int:
    if target_lang.startswith("zh") or target_lang == "ja":
        base = int(len(text) * 2.2) + 64
    else:
        base = int(len(text.split()) * 2.6) + 64
    return max(64, min(1024, base))


def build_local_prompt(
    text: str,
    hits: list[TermHit],
    context: list[tuple[str, str]],
    settings: TranslateSettings,
    reference: str = "",
    source_lang: str = "auto",
) -> str:
    """HY-MT1.5 官方推荐的“指令 + 术语参考”提示格式；不使用 system 角色。"""
    target = target_language_name(settings.target_lang)
    style = STYLES.get(settings.style, settings.style)
    lines: list[str] = []
    extra = (settings.extra_prompt or "").strip()
    if extra:
        lines.append(f"补充要求：{extra}")

    if hits:
        lines.append("参考下面的翻译：")
        seen: set[tuple[str, str]] = set()
        for hit in hits[:24]:
            pair = (hit.term.src, hit.term.dst)
            if pair in seen:
                continue
            seen.add(pair)
            lines.append(f"{hit.term.src} 翻译成 {hit.term.dst}")
        lines.append("")

    if reference:
        lines.append(f"参考译文（可润色，不要照抄错误）：{reference}")
        lines.append("")

    context_limit = max(0, int(settings.context_sentences))
    if context_limit and context:
        lines.append("上文（仅供衔接，不要重复翻译）：")
        for src, dst in context[-context_limit:]:
            lines.append(f"{src} => {dst}")
        lines.append("")

    lines.append(
        f"将以下文本翻译为{target}，风格：{style}，"
        "注意只需要输出翻译后的结果，不要额外解释："
    )
    lines.append("")
    lines.append(text)
    return "\n".join(lines)


def _supports_thinking(model: str) -> bool:
    name = (model or "").strip().lower()
    return name.startswith("deepseek-flash") or name.startswith("deepseek-v4")


HY_SPECIAL_TOKENS = (
    "<｜hy_begin▁of▁sentence｜>",
    "<｜hy_place▁holder▁no▁2｜>",
    "<｜hy_place▁holder▁no▁3｜>",
    "<｜hy_place▁holder▁no▁8｜>",
    "<｜hy_User｜>",
    "<｜hy_Assistant｜>",
)


def _strip_special(text: str) -> str:
    value = text
    for token in HY_SPECIAL_TOKENS:
        value = value.replace(token, "")
    return value.strip()


class LocalMTClient:
    """GGUF 本地翻译模型（HY-MT1.5），通过 llama-cpp-python 在进程内运行。"""

    def __init__(self, settings: TranslateSettings) -> None:
        self.settings = settings
        self._llama = None
        self._loaded_path = ""
        self._lock = threading.Lock()
        self._load_ms = 0.0

    @property
    def model_path(self) -> str:
        from . import paths

        return paths.resolve_local_mt_model(
            self.settings.local_model, self.settings.local_model_path
        )

    def close(self) -> None:
        with self._lock:
            self._llama = None
            self._loaded_path = ""

    def update_settings(self, settings: TranslateSettings) -> None:
        changed = (
            settings.local_model != self.settings.local_model
            or settings.local_model_path != self.settings.local_model_path
            or int(settings.local_gpu_layers) != int(self.settings.local_gpu_layers)
        )
        self.settings = settings
        if changed:
            self.close()

    def _load(self) -> None:
        if self._llama is not None:
            return
        path = self.model_path
        if not path:
            raise TranslationError(
                "本地翻译模型未下载。请到「设置 → 翻译服务」下载 HY-MT1.5 1.8B，"
                "或在「模型文件」中指定 GGUF 路径。"
            )
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise TranslationError(
                "缺少 llama-cpp-python。请运行：venv\\Scripts\\python.exe -m pip install "
                "llama-cpp-python==0.3.36 --extra-index-url "
                "https://abetlen.github.io/llama-cpp-python/whl/cu124"
            ) from exc

        import os

        layers = max(0, int(self.settings.local_gpu_layers))
        threads = max(2, min(16, (os.cpu_count() or 8) - 2))
        kwargs = {
            "model_path": path,
            "n_ctx": 4096,
            "n_batch": 512,
            "n_gpu_layers": layers,
            "n_threads": threads,
            "verbose": False,
            "use_mmap": True,
            "use_mlock": False,
            "offload_kqv": True,
            "chat_format": None,
        }
        started = time.perf_counter()
        try:
            self._llama = Llama(**kwargs)
        except Exception as exc:
            if layers <= 0:
                raise TranslationError(f"本地模型加载失败：{exc}") from exc
            log.warning("GPU 加载本地翻译模型失败，回退 CPU：%s", exc)
            try:
                kwargs["n_gpu_layers"] = 0
                self._llama = Llama(**kwargs)
            except Exception as exc2:
                raise TranslationError(f"本地模型加载失败：{exc2}") from exc2
        self._loaded_path = path
        self._load_ms = (time.perf_counter() - started) * 1000
        log.info("本地翻译模型已加载 path=%s layers=%s %.0fms", path, layers, self._load_ms)

    def ensure_loaded(self) -> None:
        with self._lock:
            self._load()

    def _chat(self, prompt: str, max_tokens: int) -> Iterator[dict]:
        assert self._llama is not None
        return self._llama.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max(16, int(max_tokens)),
            temperature=max(0.0, min(float(self.settings.temperature), 0.7)),
            top_k=20,
            top_p=0.6,
            repeat_penalty=1.05,
            stream=True,
        )

    def translate_stream(
        self,
        prompt: str,
        max_tokens: int,
        cancel_event: threading.Event | None = None,
        on_delta: Callback | None = None,
    ) -> tuple[str, float, float]:
        with self._lock:
            if cancel_event and cancel_event.is_set():
                raise TranslationCancelled()
            self._load()
            started = time.perf_counter()
            first_at: float | None = None
            parts: list[str] = []
            try:
                for chunk in self._chat(prompt, max_tokens):
                    if cancel_event and cancel_event.is_set():
                        raise TranslationCancelled()
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if not content:
                        continue
                    if first_at is None:
                        first_at = time.perf_counter()
                    parts.append(content)
                    if on_delta:
                        try:
                            on_delta(content)
                        except Exception:
                            log.exception("on_delta 回调异常")
            except TranslationCancelled:
                raise
            except TranslationError:
                raise
            except Exception as exc:
                raise TranslationError(f"本地模型生成失败：{exc}", retryable=True) from exc

            text = _strip_special("".join(parts)).strip()
            if not text:
                raise TranslationError("本地模型返回了空结果", retryable=True)
            now = time.perf_counter()
            ttfb = (first_at - started) * 1000 if first_at else 0.0
            return text, ttfb, (now - started) * 1000

    def test_connection(self) -> tuple[bool, str]:
        started = time.perf_counter()
        try:
            self.ensure_loaded()
            prompt = build_local_prompt(
                "こんにちは、世界。", [], [], self.settings
            )
            text, _, _ = self.translate_stream(prompt, 64)
            elapsed = (time.perf_counter() - started) * 1000
            if not text:
                return False, "本地模型返回空结果"
            return True, f"本地模型可用 · {elapsed:.0f} ms"
        except TranslationError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"本地模型测试失败：{exc}"



def iter_sse(lines: Iterable[str]) -> Iterator[dict]:
    """解析 OpenAI 兼容 SSE，产出 JSON 事件。"""
    for raw in lines:
        if not raw:
            continue
        line = raw.strip()
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            break
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            log.debug("忽略无法解析的 SSE 行: %s", line[:200])


class DeepSeekClient:
    def __init__(self, settings: TranslateSettings, api_key: str) -> None:
        if not api_key:
            raise TranslationError("未配置 DeepSeek API Key，请在设置中填写。")
        self.settings = settings
        self.api_key = api_key
        self.endpoint = settings.base_url.rstrip("/") + "/chat/completions"
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=8.0, read=max(5.0, float(settings.timeout_s)), write=15.0, pool=5.0
            ),
            follow_redirects=True,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def update_credentials(self, settings: TranslateSettings, api_key: str) -> None:
        self.settings = settings
        self.api_key = api_key
        self.endpoint = settings.base_url.rstrip("/") + "/chat/completions"
        self._client.headers.update({"Authorization": f"Bearer {api_key}"})
        self._client.timeout = httpx.Timeout(
            connect=8.0, read=max(5.0, float(settings.timeout_s)), write=15.0, pool=5.0
        )

    def _payload(
        self, messages: list[dict[str, str]], max_tokens: int, stream: bool
    ) -> dict:
        payload: dict = {
            "model": self.settings.model,
            "messages": messages,
            "stream": stream,
            "temperature": float(self.settings.temperature),
            "max_tokens": int(max_tokens),
        }
        if _supports_thinking(self.settings.model):
            # deepseek-flash / v4 默认开启思考；实时字幕默认显式关闭。
            payload["thinking"] = {
                "type": "enabled" if self.settings.thinking else "disabled"
            }
        return payload

    def translate_stream(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        cancel_event: threading.Event | None = None,
        on_delta: Callback | None = None,
    ) -> tuple[str, float, float]:
        last_error: TranslationError | None = None
        for attempt in range(2):
            if cancel_event and cancel_event.is_set():
                raise TranslationCancelled()
            try:
                return self._stream_once(messages, max_tokens, cancel_event, on_delta)
            except TranslationError as exc:
                last_error = exc
                if not exc.retryable or attempt == 1:
                    raise
                log.warning("翻译请求失败，重试一次: %s", exc)
                time.sleep(0.35)
            except httpx.HTTPError as exc:
                last_error = TranslationError(f"网络错误：{exc}", retryable=True)
                if attempt == 1:
                    raise last_error from exc
                log.warning("翻译网络错误，重试一次: %s", exc)
                time.sleep(0.35)
        raise last_error or TranslationError("翻译失败")

    def _stream_once(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        cancel_event: threading.Event | None,
        on_delta: Callback | None,
    ) -> tuple[str, float, float]:
        payload = self._payload(messages, max_tokens, stream=True)
        started = time.perf_counter()
        first_at: float | None = None
        parts: list[str] = []

        with self._client.stream("POST", self.endpoint, json=payload) as response:
            if response.status_code != 200:
                body = response.read().decode("utf-8", "replace")
                message = _extract_error(body) or f"HTTP {response.status_code}"
                raise TranslationError(
                    f"翻译接口错误：{message}", retryable=response.status_code >= 500 or response.status_code == 429
                )
            for event in iter_sse(response.iter_lines()):
                if cancel_event and cancel_event.is_set():
                    raise TranslationCancelled()
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if not content:
                    continue
                if first_at is None:
                    first_at = time.perf_counter()
                parts.append(content)
                if on_delta:
                    try:
                        on_delta(content)
                    except Exception:
                        log.exception("on_delta 回调异常")

        text = "".join(parts).strip()
        if not text:
            raise TranslationError("翻译接口返回了空结果", retryable=True)
        now = time.perf_counter()
        ttfb = (first_at - started) * 1000 if first_at else 0.0
        return text, ttfb, (now - started) * 1000

    def test_connection(self) -> tuple[bool, str]:
        payload = {
            "model": self.settings.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0,
            "stream": False,
        }
        if _supports_thinking(self.settings.model):
            payload["thinking"] = {
                "type": "enabled" if self.settings.thinking else "disabled"
            }
        started = time.perf_counter()
        try:
            response = self._client.post(self.endpoint, json=payload)
            elapsed = (time.perf_counter() - started) * 1000
            if response.status_code != 200:
                return False, _extract_error(response.text) or f"HTTP {response.status_code}"
            return True, f"连接正常 · {elapsed:.0f} ms"
        except httpx.HTTPError as exc:
            return False, f"网络错误：{exc}"


def _extract_error(body: str) -> str:
    try:
        data = json.loads(body)
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error)
        if error:
            return str(error)
        if "message" in data:
            return str(data["message"])
    except (json.JSONDecodeError, AttributeError):
        pass
    return body[:300].strip()


class TranslationService:
    """翻译入口：先查内存语料库，再调用云端 API 或本地 GGUF 模型。"""

    def __init__(self, settings: TranslateSettings, api_key: str, memory=None) -> None:
        self.settings = settings
        self.memory = memory
        self.api_key = api_key
        self.provider = _provider(settings)
        self.client = self._make_client()
        self.demo_mode = False

    def _make_client(self) -> DeepSeekClient | LocalMTClient | None:
        if self.provider == "local":
            return LocalMTClient(self.settings)
        if self.api_key:
            return DeepSeekClient(self.settings, self.api_key)
        return None

    def update_settings(self, settings: TranslateSettings, api_key: str) -> None:
        new_provider = _provider(settings)
        old = self.settings
        local_changed = new_provider == "local" and (
            settings.local_model != old.local_model
            or settings.local_model_path != old.local_model_path
            or int(settings.local_gpu_layers) != int(old.local_gpu_layers)
        )
        if new_provider != self.provider or local_changed or self.client is None:
            if self.client is not None:
                self.client.close()
            self.settings = settings
            self.api_key = api_key
            self.provider = new_provider
            self.client = self._make_client()
            return

        self.settings = settings
        self.api_key = api_key
        if new_provider == "local":
            assert isinstance(self.client, LocalMTClient)
            self.client.update_settings(settings)
        else:
            assert isinstance(self.client, DeepSeekClient)
            if api_key:
                self.client.update_credentials(settings, api_key)
            else:
                self.client.close()
                self.client = None

    def close(self) -> None:
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass

    def readiness(self) -> tuple[bool, str]:
        """返回 (是否可翻译, 给用户看的原因)。"""
        if self.demo_mode:
            return True, ""
        if self.provider == "local":
            path = ""
            if isinstance(self.client, LocalMTClient):
                path = self.client.model_path
            if not path:
                path = paths.resolve_local_mt_model(
                    self.settings.local_model, self.settings.local_model_path
                )
            if not path:
                return (
                    False,
                    "本地翻译模型未下载：请到「设置 → 翻译服务」下载 HY-MT1.5 1.8B，"
                    "或在「模型文件」中指定 GGUF 路径。",
                )
            return True, ""
        if not self.api_key:
            return False, "未配置 DeepSeek API Key，请在设置中填写。"
        return True, ""

    def warmup(self) -> None:
        """本地模型在开始同传前预热，避免第一句等待加载。"""
        if self.provider != "local" or not isinstance(self.client, LocalMTClient):
            return
        ok, reason = self.readiness()
        if not ok:
            raise TranslationError(reason)
        self.client.ensure_loaded()
        prompt = build_local_prompt("こんにちは。", [], [], self.settings)
        try:
            self.client.translate_stream(prompt, 32)
        except TranslationError:
            raise
        except Exception as exc:
            log.debug("本地翻译预热失败（不影响启动）: %s", exc)

    def translate(
        self,
        text: str,
        hits: list[TermHit],
        context: list[tuple[str, str]],
        source_lang: str,
        cancel_event: threading.Event | None = None,
        on_delta: Callback | None = None,
        allow_tm: bool = True,
    ) -> TranslationResult:
        if self.demo_mode:
            return self._demo(text, on_delta)

        target = self.settings.target_lang
        reference = ""
        if allow_tm and self.settings.use_tm and self.memory is not None:
            hit = self.memory.lookup(text)
            if hit is not None:
                miss = missing_terms(hits, hit.entry.dst)
                if not miss:
                    if on_delta:
                        on_delta(hit.entry.dst)
                    self.memory.bump(hit.entry.id)
                    return TranslationResult(
                        text=hit.entry.dst,
                        ttfb_ms=0.0,
                        total_ms=0.0,
                        model="tm",
                        via_tm=True,
                        tm_score=hit.score,
                    )
                log.debug("语料库命中但缺少术语 %s，改走模型", miss)
                if len(text) > 8 and hit.score >= max(self.settings.fuzzy_threshold, 0.88):
                    reference = hit.entry.dst

        ok, reason = self.readiness()
        if not ok or self.client is None:
            raise TranslationError(reason or "翻译服务不可用")

        max_tokens = self.settings.max_tokens or estimate_max_tokens(text, target)
        if self.provider == "local":
            assert isinstance(self.client, LocalMTClient)
            prompt = build_local_prompt(
                text,
                hits,
                context,
                self.settings,
                reference=reference,
                source_lang=source_lang,
            )
            translated, ttfb, total = self.client.translate_stream(
                prompt, max_tokens, cancel_event=cancel_event, on_delta=on_delta
            )
            model = paths.local_mt_label(self.settings.local_model)
        else:
            assert isinstance(self.client, DeepSeekClient)
            messages = build_messages(
                text,
                hits,
                context,
                self.settings,
                reference=reference,
                source_lang=source_lang,
            )
            translated, ttfb, total = self.client.translate_stream(
                messages, max_tokens, cancel_event=cancel_event, on_delta=on_delta
            )
            model = self.settings.model

        translated = _clean_output(translated)
        miss = missing_terms(hits, translated)
        return TranslationResult(
            text=translated,
            ttfb_ms=ttfb,
            total_ms=total,
            model=model,
            missing_terms=miss,
        )

    def _demo(self, text: str, on_delta: Callback | None) -> TranslationResult:
        time.sleep(0.15)
        result = f"[演示译文] {text}"
        if on_delta:
            for ch in result:
                on_delta(ch)
                time.sleep(0.005)
        return TranslationResult(result, 150.0, 200.0, "demo")

    def test_connection(self) -> tuple[bool, str]:
        if self.client is None:
            return False, self.readiness()[1] or "翻译服务不可用"
        return self.client.test_connection()


def _provider(settings: TranslateSettings) -> str:
    value = (settings.provider or "deepseek").strip().lower()
    return "local" if value in ("local", "hy-mt", "offline") else "deepseek"



def _clean_output(text: str) -> str:
    value = text.strip()
    for prefix in ("译文：", "译文:", "翻译：", "翻译:", "Translation:", "translation:"):
        if value.startswith(prefix):
            value = value[len(prefix) :].strip()
    if len(value) >= 2 and value[0] in "\"'“”‘’" and value[-1] in "\"'“”‘’":
        value = value[1:-1].strip()
    if value.startswith("```") and value.endswith("```"):
        value = value.strip("`").strip()
        if "\n" in value:
            value = value.split("\n", 1)[1].strip()
    return value
