// Offscreen document: capture tab audio, downsample to 16 kHz mono float32,
// and stream it to Local Interpreter over a local WebSocket.

let socket = null;
let context = null;
let source = null;
let processor = null;
let muted = null;
let stream = null;
let capturing = false;
let wsUrl = "ws://127.0.0.1:17866/audio";
let retryTimer = null;
let title = "";

function post(state, message) {
  try {
    chrome.runtime.sendMessage({ type: "status", state, message: message || "" });
  } catch (error) {
    // service worker 可能正在休眠
  }
}

function downsample(input, inRate, outRate = 16000) {
  if (inRate === outRate) return input;
  const ratio = inRate / outRate;
  const length = Math.floor(input.length / ratio);
  const output = new Float32Array(length);
  for (let i = 0; i < length; i += 1) {
    const position = i * ratio;
    const index = Math.floor(position);
    const fraction = position - index;
    const next = Math.min(index + 1, input.length - 1);
    output[i] = input[index] * (1 - fraction) + input[next] * fraction;
  }
  return output;
}

function connect() {
  if (!capturing) return;
  try {
    socket = new WebSocket(wsUrl);
  } catch (error) {
    scheduleRetry();
    return;
  }
  socket.binaryType = "arraybuffer";
  socket.onopen = () => {
    post("capturing", title);
    try {
      socket.send(JSON.stringify({ type: "hello", title }));
    } catch (error) {
      // ignore
    }
  };
  socket.onclose = () => {
    socket = null;
    if (capturing) scheduleRetry();
  };
  socket.onerror = () => {
    try {
      socket.close();
    } catch (error) {
      // ignore
    }
  };
}

function scheduleRetry() {
  if (retryTimer || !capturing) return;
  retryTimer = setTimeout(() => {
    retryTimer = null;
    connect();
  }, 1000);
}

async function startCapture(streamId, url, tabTitle) {
  await stopCapture(false);
  wsUrl = url || wsUrl;
  title = tabTitle || "";

  stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId,
      },
    },
    video: false,
  });

  context = new AudioContext({ sampleRate: 48000 });
  await context.resume();
  source = context.createMediaStreamSource(stream);
  // tabCapture 会让原标签页静音，这里把声音接回扬声器。
  source.connect(context.destination);

  processor = context.createScriptProcessor(2048, 1, 1);
  muted = context.createGain();
  muted.gain.value = 0;
  processor.connect(muted);
  muted.connect(context.destination);

  processor.onaudioprocess = (event) => {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    const input = event.inputBuffer.getChannelData(0);
    const output = downsample(input, context.sampleRate, 16000);
    if (!output.length) return;
    try {
      socket.send(output.buffer);
    } catch (error) {
      // 下一帧重试
    }
  };

  source.connect(processor);
  capturing = true;
  connect();
  post("capturing", title);

  const track = stream.getAudioTracks()[0];
  if (track) {
    track.onended = () => stopCapture(true);
  }
}

async function stopCapture(notify = true) {
  capturing = false;
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
  if (socket) {
    try {
      socket.close();
    } catch (error) {
      // ignore
    }
    socket = null;
  }
  if (processor) {
    try {
      processor.disconnect();
    } catch (error) {
      // ignore
    }
    processor.onaudioprocess = null;
    processor = null;
  }
  if (source) {
    try {
      source.disconnect();
    } catch (error) {
      // ignore
    }
    source = null;
  }
  if (muted) {
    try {
      muted.disconnect();
    } catch (error) {
      // ignore
    }
    muted = null;
  }
  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }
  if (context) {
    try {
      await context.close();
    } catch (error) {
      // ignore
    }
    context = null;
  }
  if (notify) post("idle", "");
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.target !== "offscreen") return;
  if (message.type === "start") {
    startCapture(message.streamId, message.wsUrl, message.title).catch(async (error) => {
      console.error("tab capture failed", error);
      await stopCapture(false);
      const detail = `${error.name || "Error"}${
        error.constraint ? ` (${error.constraint})` : ""
      }: ${error.message || String(error)}`;
      post("error", detail);
    });
    sendResponse({ ok: true });
  } else if (message.type === "stop") {
    stopCapture(true).then(() => sendResponse({ ok: true }));
    return true;
  }
});
