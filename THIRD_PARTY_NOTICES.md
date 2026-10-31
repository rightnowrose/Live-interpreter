# 第三方组件与模型声明

Local Interpreter 自身代码不包含任何第三方 API Key；安装包内的默认配置
`api_key_enc` 为空。用户需要自行填写 DeepSeek API Key，或者使用本地翻译模型。

## 随安装包分发的模型

### faster-whisper large-v3-turbo

- 仓库：https://hf-mirror.com/mobiuslabsgmbh/faster-whisper-large-v3-turbo
- 上游：OpenAI Whisper large-v3-turbo（MIT License）
- 用途：本地语音识别
- 安装包内路径：`models/large-v3-turbo/`

### Tencent HY-MT1.5-1.8B-GGUF（Q4_K_M）

- 仓库：https://hf-mirror.com/tencent/HY-MT1.5-1.8B-GGUF
- 许可：Tencent HY Community License Agreement（**不适用于欧盟、英国和韩国**）
- 许可全文：`LICENSES/HY-MT1.5-License.txt`
- 用途：本地日语/中文等翻译
- 安装包内路径：`models/HY-MT1.5-1.8B-GGUF/HY-MT1.5-1.8B-Q4_K_M.gguf`

分发时必须附带以下 Notice：

> Tencent HY is licensed under the Tencent HY Community License Agreement,
> Copyright © 2025 Tencent. All Rights Reserved. The trademark rights of
> “Tencent HY” are owned by Tencent or its affiliate.

## 主要运行时组件

| 组件 | 许可 | 项目 |
|---|---|---|
| PySide6 / Qt | LGPL-3.0（动态链接） | https://www.qt.io/ |
| faster-whisper | MIT | https://github.com/SYSTRAN/faster-whisper |
| CTranslate2 | MIT | https://github.com/OpenNMT/CTranslate2 |
| llama-cpp-python / llama.cpp | MIT | https://github.com/abetlen/llama-cpp-python |
| onnxruntime | MIT | https://github.com/microsoft/onnxruntime |
| Silero VAD | MIT | https://github.com/snakers4/silero-vad |
| soundcard | BSD-3-Clause | https://github.com/bastibe/SoundCard |
| soxr | LGPL-2.1+ | https://github.com/dofuuz/python-soxr |
| NumPy | BSD-3-Clause | https://numpy.org/ |
| tokenizers | Apache-2.0 | https://github.com/huggingface/tokenizers |
| Hugging Face Hub | Apache-2.0 | https://github.com/huggingface/huggingface_hub |
| PyAV / FFmpeg | BSD / LGPL | https://github.com/PyAV-Org/PyAV |
| httpx | BSD-3-Clause | https://github.com/encode/httpx |
| websockets | BSD-3-Clause | https://github.com/python-websockets/websockets |
| openpyxl | MIT | https://openpyxl.readthedocs.io/ |
| Pillow（仅构建图标时使用） | MIT-CMU | https://python-pillow.org/ |

## 其他可下载模型

安装包不包含以下模型，但设置页保留了入口和下载地址，下载后放入
`%LOCALAPPDATA%\LocalInterpreter\models\` 或在设置中指定目录即可：

- faster-whisper large-v3 / medium / small / base / tiny
- kotoba-whisper-v2.0-faster
- kotoba-whisper-bilingual-v1.0-faster
- HY-MT1.5-7B-GGUF（质量优先，6 GB 显存建议调低 GPU 层数）

完整地址见 `models.json` 与设置页的模型状态行。
