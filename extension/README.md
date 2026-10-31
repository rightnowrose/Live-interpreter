# 浏览器标签页音频扩展（Edge / Chrome）

这个扩展把**当前标签页**的音频降采样为 16 kHz 单声道 float32，通过本机 WebSocket 发送给 RoseSI。

## 安装（一次性）

1. 打开 Edge：地址栏输入 `edge://extensions/`；Chrome：`chrome://extensions/`。
2. 打开右上角 **开发者模式**。
3. 点击 **加载解压缩的扩展**，选择本目录（包含 `manifest.json` 的 `extension` 文件夹）。
4. 建议把扩展固定到工具栏。

## 使用

1. 启动 RoseSI。
2. 工作台 → 设置 → 音频源 → **浏览器标签页（扩展）** → 保存并应用。
3. 点击字幕窗的「开始」。
4. 切换到要翻译的标签页（视频/会议/网页），点击工具栏上的扩展图标。
   - 徽标显示 **ON** 表示正在发送音频。
   - 再次点击同一标签页的图标即可停止。
5. 停止同传或关闭标签页会自动断开。

## 工作原理

- Service Worker 调 `chrome.tabCapture.getMediaStreamId` 获取标签页音频。
- Offscreen 文档用 `getUserMedia({chromeMediaSource:'tabCapture'})` 接收音频，
  然后把声音接回扬声器（否则标签页会被浏览器静音），同时用 `ScriptProcessor`
  降采样到 16 kHz，通过 `ws://127.0.0.1:17866/audio` 发送二进制 float32。
- 应用侧 `app/tab_capture.py` 接收并送入 VAD/ASR 管线。
- 仅绑定 `127.0.0.1`，音频不经过网络。

## 端口冲突

默认端口 `17866`。如果被占用：

1. 修改 `service-worker.js` 顶部的 `WS_URL` 端口；
2. 在 `config.json` 的 `audio.ws_port` 改为同一端口（关闭程序后编辑），或在代码中调整设置；
3. 重新加载扩展。

## 已知限制

- 只捕获标签页正在播放的声音；标签页静音/无声音时没有数据。
- `ScriptProcessor` 已废弃但兼容性最好；每 2048 帧（约 43 ms）发送一次。
- 扩展需要 Edge/Chrome 116+（Offscreen API 与 `getMediaStreamId`）。
