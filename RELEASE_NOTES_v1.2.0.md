# RoseSI 1.2.0

RoseSI 的首个公开版本：面向日语直播、会议与视频的 Windows 实时字幕 / 同传工具。

## 亮点

- **双 ASR 后端**：Parakeet TDT 0.6B JA（ONNX/CUDA，直播低延迟）+ faster-whisper large-v3-turbo（兼容/备用）。
- **双翻译后端**：DeepSeek 流式翻译，或完全本地的 HY-MT1.5-1.8B GGUF。
- **面向直播的断句**：VAD 候选断点 + 语义端点保持、Parakeet 滑动预览、翻译积压丢弃与队列/落后显示。
- **术语与语料**：内置 288 条日中直播/Bilibili Vtuber 基础术语库，支持多个自建库、候选审核和可选 AI 预审。
- **字幕窗**：专注 / 双语 / 学习三种模式，日文/中文字体分离，历史摘要，术语/记忆命中，回到最新，工具栏自动隐藏，多屏定位。
- **工作台**：可折叠分组侧栏、全局开始/停止、会话记录、导出、设置；内置五十音图。
- **RoseSI 品牌**：新名称、玫瑰图标、深紫 + 樱花粉二次元界面。

## 安装

1. 下载全部安装分卷：
   - `RoseSI-1.2.0-Setup.exe.part001`
   - `RoseSI-1.2.0-Setup.exe.part002`
2. 合并：

   ```bat
   copy /b RoseSI-1.2.0-Setup.exe.part001 + RoseSI-1.2.0-Setup.exe.part002 RoseSI-1.2.0-Setup.exe
   ```

3. 用 `SHA256.txt` 校验合并后的文件。
4. 双击安装，按提示完成。

安装包内置：

- Parakeet TDT 0.6B JA（ONNX，日语直播首选）
- HY-MT1.5-1.8B Q4_K_M（本地日→中翻译）
- CUDA 12 运行时与 cuDNN 9（Parakeet GPU 推理所需）

faster-whisper large-v3-turbo、Kotoba、HY-MT 7B 等其他模型不内置，可在应用内下载，或从 `packaging/models.json` 获取下载地址。

## 系统要求

- Windows 10 2004+ / Windows 11 x64
- 约 5 GB 磁盘空间（安装版）
- 推荐 NVIDIA GPU；CPU 可运行但实时性有限

## 数据与隐私

- 不包含任何 DeepSeek API Key。
- API Key 只保存在本机 `%LOCALAPPDATA%\LocalInterpreter`，使用 Windows DPAPI 加密。
- 本地 HY-MT 模式不联网；DeepSeek 模式只发送待翻译文本与术语，不发送音频。

## 已知限制

- 目前仅支持 Windows。
- 系统声音是设备级环回，不能按应用隔离；按标签页请使用浏览器扩展。
- 翻译按句提交，不是逐词同传；静音断句决定延迟下限。

## 许可证

代码采用 MIT License。模型权重和第三方运行时遵循各自许可证，详见 `LICENSES/` 和 `THIRD_PARTY_NOTICES.md`。
