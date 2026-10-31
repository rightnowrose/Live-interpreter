// RoseSI · 标签页音频捕获（Edge / Chrome MV3）
// 点击工具栏图标：开始/停止捕获当前标签页；音频通过 WebSocket 发送到本机应用。

const WS_URL = "ws://127.0.0.1:17866/audio";
let currentTabId = null;
let starting = false;

async function ensureOffscreen() {
  try {
    await chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["USER_MEDIA"],
      justification: "Capture tab audio and stream it to the local interpreter",
    });
  } catch (error) {
    // 已经存在时会抛错；后续 sendMessage 会给出更准确的失败原因。
  }
}

function getStreamId(tabId) {
  return new Promise((resolve, reject) => {
    chrome.tabCapture.getMediaStreamId({ targetTabId: tabId }, (streamId) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else if (!streamId) {
        reject(new Error("无法获取标签页音频（请确认标签页正在播放声音）"));
      } else {
        resolve(streamId);
      }
    });
  });
}

function badge(text, color) {
  chrome.action.setBadgeBackgroundColor({ color: color || "#35c26b" });
  chrome.action.setBadgeText({ text: text || "" });
}

async function start(tab) {
  if (!tab || !tab.id || starting) return;
  starting = true;
  badge("…", "#f0a020");
  try {
    await ensureOffscreen();
    const streamId = await getStreamId(tab.id);
    await chrome.runtime.sendMessage({
      target: "offscreen",
      type: "start",
      streamId,
      tabId: tab.id,
      title: tab.title || "",
      wsUrl: WS_URL,
    });
    currentTabId = tab.id;
    badge("ON", "#35c26b");
    chrome.action.setTitle({
      tabId: tab.id,
      title: "正在发送此标签页音频 · 再次点击停止",
    });
  } catch (error) {
    console.error(error);
    badge("!", "#e5484d");
    chrome.action.setTitle({ title: String(error.message || error) });
    currentTabId = null;
  } finally {
    starting = false;
  }
}

async function stop() {
  try {
    await chrome.runtime.sendMessage({ target: "offscreen", type: "stop" });
  } catch (error) {
    // offscreen 可能已经关闭
  }
  currentTabId = null;
  badge("", "#35c26b");
  chrome.action.setTitle({ title: "捕获当前标签页音频到 RoseSI" });
}

chrome.action.onClicked.addListener(async (tab) => {
  if (currentTabId !== null && tab.id === currentTabId) {
    await stop();
  } else {
    await stop();
    await start(tab);
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === currentTabId) stop();
});

chrome.runtime.onMessage.addListener((message) => {
  if (!message || message.type !== "status") return;
  if (message.state === "error") {
    badge("!", "#e5484d");
    chrome.action.setTitle({ title: message.message || "标签页音频捕获失败" });
  } else if (message.state === "idle") {
    badge("", "#35c26b");
  } else if (message.state === "capturing") {
    badge("ON", "#35c26b");
  }
});
