RoseSI Lite 在线版

这是不内置模型的绿色版。程序本身包含 Parakeet 运行库和 CUDA/cuDNN，但语音识别和本地翻译模型需要首次运行时下载。

首次使用：
1. 双击 RoseSI.exe。
2. 打开「工作台 → 设置 → 本地识别」。
3. Parakeet TDT 0.6B JA 状态显示“缺少文件”时，点「下载模型」，约 1.2 GB。下载完成后即可离线识别。
4. 如果要使用本地翻译：设置 → 翻译服务 → 翻译方式选「本地模型」→ 下载 HY-MT1.5 1.8B（约 1.1 GB）。
5. 如果使用 DeepSeek 翻译：填入自己的 API Key，不需要下载翻译模型。

模型也可以手动放到：
  %LOCALAPPDATA%\LocalInterpreter\models\

其他 Whisper/Kotoba 模型在设置里选择后，按页面提示下载即可。

注意：模型下载需要网络；下载的是模型文件，不包含任何人的 API Key。
