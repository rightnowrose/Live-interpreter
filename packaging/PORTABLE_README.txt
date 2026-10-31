RoseSI 1.2.0（便携版）

1. 双击 RoseSI.exe 即可运行，无需安装 Python。
2. 已内置：
   - Parakeet TDT 0.6B JA（ONNX，日语直播首选）
   - HY-MT1.5-1.8B Q4_K_M（离线翻译）
   Whisper large-v3-turbo 等其他模型不在包内，可在设置中直接下载或查看 models.json。
3. 首次启动在「工作台 → 设置」选择：
   - 翻译方式：本地模型（离线，HY-MT1.5）——无需 API Key
   - 或 DeepSeek API——需要填写你自己的 API Key
4. 数据保存在 %LOCALAPPDATA%\LocalInterpreter（沿用旧目录名，便于升级保留配置），不写入安装目录。
5. 浏览器标签页音频：设置页「打开扩展目录」，按提示在 Edge/Chrome 加载。
6. 更多模型和下载地址见 models.json 与 README.md。

安装包不会包含任何 API Key。若从旧版本升级，旧配置中的 Key 仅保存在本机 DPAPI 中。
