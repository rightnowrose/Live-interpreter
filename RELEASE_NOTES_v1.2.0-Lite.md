# RoseSI 1.2.0 Lite（在线版）

RoseSI 的轻量在线安装版：程序本体不包含语音识别和本地翻译模型，首次使用时在应用内下载。

## 和标准版的区别

| | 标准版 | Lite 在线版 |
| --- | --- | --- |
| 安装包 | 约 3.41 GB，拆两个分卷 | 约 1.2 GB，单文件 |
| 安装后 | 约 5.6 GB | 约 3.4 GB |
| Parakeet | 已内置 | 首次在设置里下载（约 1.2 GB） |
| HY-MT1.5 | 已内置 | 首次在设置里下载（约 1.1 GB） |
| 其他 Whisper/Kotoba | 需下载 | 需下载 |
| DeepSeek API | 留空，用户自填 | 留空，用户自填 |

## 安装

1. 下载 `RoseSI-1.2.0-Lite-Setup.exe`。
2. 用 `SHA256-Lite.txt` 校验。
3. 双击安装。

## 首次运行

1. 打开「工作台 → 设置 → 本地识别」。
2. 在 Parakeet 模型状态旁点「下载模型」，下载约 1.2 GB；完成后即可离线日语识别。
3. 使用 DeepSeek 翻译：在「翻译服务」填自己的 API Key。
4. 使用本地翻译：翻译方式选「本地模型」，在「本地模型」旁点「下载模型」，下载约 1.1 GB HY-MT1.5。
5. 其他 Whisper/Kotoba 模型仍在设置中保留入口，选择后按提示下载。

模型下载默认走 `hf-mirror.com`；模型文件保存在 `%LOCALAPPDATA%\LocalInterpreter\models`，升级/重装不会重复下载。

## 包含内容

- RoseSI 程序与二次元界面
- Parakeet ONNX 推理运行时（onnxruntime-gpu）
- llama.cpp CUDA 运行时
- CUDA 12 / cuDNN 9 运行库
- 内置 288 条日中直播/Bilibili Vtuber 基础术语库

不包含：

- 任何模型权重（Parakeet/HY-MT/Whisper/Kotoba）
- 任何 DeepSeek API Key
- 用户配置、会话记录、术语库、语料库

## 系统要求

- Windows 10 2004+ / Windows 11 x64
- 推荐 NVIDIA GPU（RTX 3060 6 GB 或以上）；CPU 可运行但实时性有限
- 首次下载模型需要网络

## 数据与隐私

- API Key 只保存在本机 `%LOCALAPPDATA%\LocalInterpreter\config.json`，使用 Windows DPAPI 加密。
- 本地 HY-MT 模式不联网；DeepSeek 模式只发送待翻译文本与术语，不发送音频。
- 模型从 hf-mirror 下载，不会上传任何用户数据。

## 许可证

代码采用 MIT License。模型权重和第三方运行时遵循各自许可证；下载模型前请阅读对应模型页面。HY-MT1.5 使用腾讯 HY 社区许可（不含欧盟/英国/韩国），商用前请自行确认。
