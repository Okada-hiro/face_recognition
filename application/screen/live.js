const screenEl = document.querySelector(".phone-screen");
const heroTitle = document.getElementById("hero-title");
const heroSubtitle = document.getElementById("hero-subtitle");
const statePill = document.getElementById("state-pill");
const orbitText = document.getElementById("orbit-text");
const feedBadge = document.getElementById("feed-badge");
const targetLabel = document.getElementById("target-label");
const metaTarget = document.getElementById("meta-target");
const metaIdentity = document.getElementById("meta-identity");
const metaMode = document.getElementById("meta-mode");
const bubbleUser = document.getElementById("bubble-user");
const bubbleAi = document.getElementById("bubble-ai");
const dialogueStage = document.getElementById("dialogue-stage");
const assistantFace = document.getElementById("assistant-face");
const cameraVideo = document.getElementById("camera-video");
const feedImage = document.getElementById("feed-image");
const captureCanvas = document.getElementById("capture-canvas");
const bootOverlay = document.getElementById("app-boot");
const bootStartButton = document.getElementById("boot-start");
const bootCopy = document.getElementById("boot-copy");
const bootNote = document.getElementById("boot-note");
const debugPill = document.getElementById("live-debug-pill");
const statusTime = document.getElementById("status-time");
const netPill = document.getElementById("net-pill");

const STATES = {
  idle: {
    pill: "IDLE",
    title: "待機中",
    subtitle: "人が近づくと顔認識と会話を開始します。",
    orbit: "STANDBY",
    badge: "No Target",
    target: "未検知",
    identity: "Unknown",
    mode: "Standby",
    user: "……",
    ai: "受付の準備ができています。",
    dialogue: "Waiting",
  },
  detecting: {
    pill: "SCAN",
    title: "人物を検知しました",
    subtitle: "前方の人物を追跡しています。",
    orbit: "TRACKING",
    badge: "Human Detected",
    target: "1 Person",
    identity: "Analyzing...",
    mode: "Person Detection",
    user: "……",
    ai: "人物を確認しています。",
    dialogue: "Tracking",
  },
  recognized: {
    pill: "MATCH",
    title: "顔認識に成功",
    subtitle: "社員データベースとの照合が完了しました。",
    orbit: "IDENTITY LOCK",
    badge: "Face Recognized",
    target: "Face Locked",
    identity: "Recognized",
    mode: "Face Recognition",
    user: "……",
    ai: "こんにちは。",
    dialogue: "Matched",
  },
  listening: {
    pill: "LISTEN",
    title: "AIが聞いています",
    subtitle: "用件を音声で受け付けています。",
    orbit: "LISTENING",
    badge: "Mic Active",
    target: "Speaking User",
    identity: "Recognized",
    mode: "Speech Input",
    user: "……",
    ai: "……",
    dialogue: "Listening",
  },
  thinking: {
    pill: "THINK",
    title: "回答を考えています",
    subtitle: "音声と認識情報をもとに返答を生成しています。",
    orbit: "REASONING",
    badge: "Processing",
    target: "Context Ready",
    identity: "Recognized",
    mode: "Response Planning",
    user: "……",
    ai: "少々お待ちください。",
    dialogue: "Thinking",
  },
  speaking: {
    pill: "SPEAK",
    title: "AIが話しています",
    subtitle: "案内内容を音声で返答しています。",
    orbit: "VOICE OUT",
    badge: "Voice Reply",
    target: "Engaged",
    identity: "Recognized",
    mode: "Speech Output",
    user: "……",
    ai: "案内を開始します。",
    dialogue: "Speaking",
  },
  farewell: {
    pill: "BYE",
    title: "見送りモード",
    subtitle: "会話を終えて待機に戻ります。",
    orbit: "SESSION END",
    badge: "Leaving",
    target: "Exit Detected",
    identity: "Recognized",
    mode: "Farewell",
    user: "ありがとうございました。",
    ai: "ありがとうございました。お気をつけて。",
    dialogue: "Farewell",
  },
};

const runtime = {
  frameCount: 0,
  stream: null,
  audioContext: null,
  sourceInput: null,
  processor: null,
  ws: null,
  frameTimerId: null,
  busyFrame: false,
  started: false,
  speaking: false,
  thinking: false,
  listening: false,
  recognizedPersonId: null,
  latestPersonCount: 0,
  latestFaceCount: 0,
  latestIntervalMs: 800,
  latestTrackEvents: [],
  latestUserText: "……",
  latestAiText: "受付の準備ができています。",
  currentAiBubbleText: "",
  currentIdentity: "Unknown",
  currentMode: "Standby",
  currentTarget: "未検知",
  bootBlocked: false,
  blinkTimerId: null,
  processLoopActive: false,
  audioMetaQueue: [],
  audioQueue: [],
  sentenceDoneMap: new Map(),
  pendingOrderedAudio: new Map(),
  expectedSentenceId: 1,
  expectedChunkId: 1,
  nextStartTime: 0,
  currentSourceNode: null,
  jitterPrimed: false,
};

function updateClock() {
  const now = new Date();
  statusTime.textContent = now.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
}

function applyState(state, overrides = {}) {
  const config = { ...STATES[state], ...overrides };
  screenEl.dataset.state = state;
  heroTitle.textContent = config.title;
  heroSubtitle.textContent = config.subtitle;
  statePill.textContent = config.pill;
  orbitText.textContent = config.orbit;
  feedBadge.textContent = config.badge;
  targetLabel.textContent = String(config.badge || "").toLowerCase();
  metaTarget.textContent = config.target;
  metaIdentity.textContent = config.identity;
  metaMode.textContent = config.mode;
  bubbleUser.textContent = config.user;
  bubbleAi.textContent = config.ai;
  dialogueStage.textContent = config.dialogue;
}

function computeNextInterval(personCount, faceCount) {
  if (faceCount > 0) return 300;
  if (personCount > 0) return 500;
  return 800;
}

function inferVisualState() {
  if (runtime.speaking) return "speaking";
  if (runtime.thinking) return "thinking";
  if (runtime.listening) return "listening";
  if (runtime.recognizedPersonId || runtime.latestFaceCount > 0) return "recognized";
  if (runtime.latestPersonCount > 0) return "detecting";
  return "idle";
}

function refreshVisualState() {
  const state = inferVisualState();
  const identity = runtime.recognizedPersonId || (runtime.latestFaceCount > 0 ? "Guest" : "Unknown");
  const target =
    runtime.latestFaceCount > 0
      ? "Face Locked"
      : runtime.latestPersonCount > 0
        ? `${runtime.latestPersonCount} Person`
        : "未検知";
  const mode =
    state === "speaking"
      ? "Speech Output"
      : state === "thinking"
        ? "Response Planning"
        : state === "listening"
          ? "Speech Input"
          : state === "recognized"
            ? "Face Recognition"
            : state === "detecting"
              ? "Person Detection"
              : "Standby";
  const subtitle =
    state === "recognized" && runtime.recognizedPersonId
      ? `${runtime.recognizedPersonId} さんを認識しました。`
      : STATES[state].subtitle;
  const aiText =
    runtime.currentAiBubbleText ||
    runtime.latestAiText ||
    STATES[state].ai;
  applyState(state, {
    identity,
    target,
    mode,
    subtitle,
    user: runtime.latestUserText,
    ai: aiText,
  });
  debugPill.textContent = `vision ${runtime.latestPersonCount}/${runtime.latestFaceCount} | ${state} | ${runtime.latestIntervalMs}ms`;
}

function scheduleNextFrame(delayMs) {
  if (runtime.frameTimerId) clearTimeout(runtime.frameTimerId);
  runtime.frameTimerId = window.setTimeout(captureAndSendFrame, delayMs);
}

function resetOrderedAudioState() {
  runtime.audioMetaQueue = [];
  runtime.audioQueue = [];
  runtime.pendingOrderedAudio.clear();
  runtime.sentenceDoneMap.clear();
  runtime.expectedSentenceId = 1;
  runtime.expectedChunkId = 1;
  runtime.nextStartTime = runtime.audioContext ? runtime.audioContext.currentTime : 0;
  runtime.jitterPrimed = false;
  runtime.currentSourceNode = null;
}

function makeChunkKey(sentenceId, chunkId) {
  return `${sentenceId}:${chunkId}`;
}

function flushOrderedAudio() {
  while (true) {
    const key = makeChunkKey(runtime.expectedSentenceId, runtime.expectedChunkId);
    const nextPacket = runtime.pendingOrderedAudio.get(key);
    if (nextPacket) {
      runtime.pendingOrderedAudio.delete(key);
      runtime.audioQueue.push(nextPacket);
      runtime.expectedChunkId += 1;
      processAudioQueue();
      continue;
    }
    const doneInfo = runtime.sentenceDoneMap.get(runtime.expectedSentenceId);
    if (doneInfo && runtime.expectedChunkId > doneInfo.lastChunkId) {
      runtime.expectedSentenceId += 1;
      runtime.expectedChunkId = 1;
      continue;
    }
    break;
  }
}

function queueOrderedChunk(meta, rawBytes) {
  runtime.pendingOrderedAudio.set(makeChunkKey(meta.sentence_id, meta.chunk_id), {
    meta,
    rawBytes,
    enqueuedAt: performance.now(),
  });
  flushOrderedAudio();
}

function getBufferedAudioMs() {
  return runtime.audioQueue.reduce((sum, packet) => {
    const int16Data = new Int16Array(packet.rawBytes);
    return sum + (int16Data.length / 16000) * 1000;
  }, 0);
}

function stopAudioPlayback() {
  if (runtime.currentSourceNode) {
    try {
      runtime.currentSourceNode.stop();
    } catch (error) {
      console.debug(error);
    }
  }
  resetOrderedAudioState();
}

async function processAudioQueue() {
  if (runtime.processLoopActive || !runtime.audioContext) return;
  runtime.processLoopActive = true;
  try {
    while (runtime.audioQueue.length > 0) {
      if (runtime.audioContext.state === "suspended") {
        await runtime.audioContext.resume();
      }
      const packet = runtime.audioQueue.shift();
      const int16Data = new Int16Array(packet.rawBytes);
      const float32Data = new Float32Array(int16Data.length);
      for (let i = 0; i < int16Data.length; i += 1) {
        float32Data[i] = int16Data[i] / 32768;
      }
      const audioBuffer = runtime.audioContext.createBuffer(1, float32Data.length, 16000);
      audioBuffer.getChannelData(0).set(float32Data);
      const source = runtime.audioContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(runtime.audioContext.destination);
      if (runtime.nextStartTime < runtime.audioContext.currentTime) {
        runtime.nextStartTime = runtime.audioContext.currentTime;
      }
      source.start(runtime.nextStartTime);
      runtime.currentSourceNode = source;
      runtime.nextStartTime += audioBuffer.duration;
    }
  } finally {
    runtime.processLoopActive = false;
  }
}

async function connectVoiceSocket() {
  const wsProtocol = window.location.protocol === "https:" ? "wss://" : "ws://";
  const socket = new WebSocket(`${wsProtocol}${window.location.host}/ws`);
  socket.binaryType = "arraybuffer";

  socket.onopen = () => {
    netPill.textContent = "Online";
    runtime.ws = socket;
  };

  socket.onmessage = async (event) => {
    if (event.data instanceof ArrayBuffer) {
      const meta = runtime.audioMetaQueue.shift();
      if (meta) {
        queueOrderedChunk(meta, event.data);
      } else {
        runtime.audioQueue.push({ meta: null, rawBytes: event.data, enqueuedAt: performance.now() });
        processAudioQueue();
      }
      return;
    }

    const data = JSON.parse(event.data);
    if (data.status === "system_info") {
      runtime.latestAiText = data.message;
      runtime.currentAiBubbleText = "";
      if (data.message.includes("接近")) {
        runtime.recognizedPersonId = runtime.recognizedPersonId || runtime.currentIdentity;
      }
    } else if (data.status === "processing") {
      runtime.listening = data.message.includes("聞いています");
      runtime.thinking = data.message.includes("思考中");
      if (runtime.thinking) runtime.listening = false;
    } else if (data.status === "transcribed") {
      runtime.latestUserText = data.question_text || "……";
      runtime.listening = false;
      runtime.thinking = true;
    } else if (data.status === "reply_chunk") {
      runtime.speaking = true;
      runtime.thinking = false;
      runtime.currentAiBubbleText += data.text_chunk || "";
      runtime.latestAiText = runtime.currentAiBubbleText;
    } else if (data.status === "audio_chunk_meta") {
      runtime.audioMetaQueue.push(data);
    } else if (data.status === "audio_sentence_done") {
      runtime.sentenceDoneMap.set(data.sentence_id, { lastChunkId: data.last_chunk_id });
      flushOrderedAudio();
    } else if (data.status === "complete") {
      runtime.speaking = false;
      runtime.thinking = false;
      runtime.listening = false;
      if (data.answer_text) {
        runtime.latestAiText = data.answer_text;
      }
      runtime.currentAiBubbleText = "";
      resetOrderedAudioState();
    } else if (data.status === "interrupt") {
      stopAudioPlayback();
      runtime.speaking = false;
    } else if (data.status === "ignored") {
      runtime.listening = false;
      runtime.thinking = false;
    }
    refreshVisualState();
  };

  socket.onclose = () => {
    runtime.ws = null;
    netPill.textContent = "Reconnect";
  };

  socket.onerror = () => {
    netPill.textContent = "Error";
  };

  return new Promise((resolve, reject) => {
    socket.addEventListener("open", () => resolve(socket), { once: true });
    socket.addEventListener("error", () => reject(new Error("WebSocket connection failed.")), { once: true });
  });
}

async function initMedia() {
  runtime.stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: "user" },
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  cameraVideo.srcObject = runtime.stream;
  await cameraVideo.play();

  runtime.audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
  const audioTracks = new MediaStream(runtime.stream.getAudioTracks());
  runtime.sourceInput = runtime.audioContext.createMediaStreamSource(audioTracks);
  runtime.processor = runtime.audioContext.createScriptProcessor(512, 1, 1);
  runtime.processor.onaudioprocess = (event) => {
    if (!runtime.ws || runtime.ws.readyState !== WebSocket.OPEN) return;
    runtime.ws.send(event.inputBuffer.getChannelData(0).buffer);
  };
  runtime.sourceInput.connect(runtime.processor);
  runtime.processor.connect(runtime.audioContext.destination);
}

async function captureAndSendFrame() {
  if (!runtime.stream || runtime.busyFrame || !cameraVideo.videoWidth) return;
  runtime.busyFrame = true;
  try {
    const width = 720;
    const scale = width / cameraVideo.videoWidth;
    const height = Math.max(1, Math.round(cameraVideo.videoHeight * scale));
    captureCanvas.width = width;
    captureCanvas.height = height;
    const ctx = captureCanvas.getContext("2d");
    ctx.drawImage(cameraVideo, 0, 0, width, height);
    const blob = await new Promise((resolve) => captureCanvas.toBlob(resolve, "image/jpeg", 0.88));
    const form = new FormData();
    form.append("frame", blob, "frame.jpg");
    const response = await fetch("/api/live-frame", { method: "POST", body: form });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    const imageBlob = await response.blob();
    feedImage.src = URL.createObjectURL(imageBlob);
    runtime.frameCount += 1;
    runtime.latestPersonCount = Number(response.headers.get("x-person-count") || "0");
    runtime.latestFaceCount = Number(response.headers.get("x-face-count") || "0");
    runtime.recognizedPersonId = response.headers.get("x-primary-person-id") || runtime.recognizedPersonId;
    runtime.latestTrackEvents = JSON.parse(response.headers.get("x-track-events") || "[]");
    runtime.latestIntervalMs = computeNextInterval(runtime.latestPersonCount, runtime.latestFaceCount);
    runtime.currentIdentity = runtime.recognizedPersonId || (runtime.latestFaceCount > 0 ? "Guest" : "Unknown");
    runtime.currentTarget =
      runtime.latestFaceCount > 0
        ? "Face Locked"
        : runtime.latestPersonCount > 0
          ? `${runtime.latestPersonCount} Person`
          : "未検知";
    if (!runtime.latestPersonCount && !runtime.latestFaceCount && !runtime.speaking && !runtime.thinking && !runtime.listening) {
      runtime.recognizedPersonId = null;
    }
    refreshVisualState();
    scheduleNextFrame(runtime.latestIntervalMs);
  } catch (error) {
    debugPill.textContent = `frame error: ${String(error)}`;
    scheduleNextFrame(1000);
  } finally {
    runtime.busyFrame = false;
  }
}

function stopRuntime() {
  if (runtime.frameTimerId) clearTimeout(runtime.frameTimerId);
  if (runtime.processor) runtime.processor.disconnect();
  if (runtime.sourceInput) runtime.sourceInput.disconnect();
  if (runtime.audioContext) runtime.audioContext.close();
  if (runtime.stream) {
    for (const track of runtime.stream.getTracks()) track.stop();
  }
  if (runtime.ws) runtime.ws.close();
}

function queueBlink(delay) {
  if (runtime.blinkTimerId) clearTimeout(runtime.blinkTimerId);
  runtime.blinkTimerId = window.setTimeout(() => {
    assistantFace.classList.add("is-blinking");
    window.setTimeout(() => assistantFace.classList.remove("is-blinking"), 140);
    queueBlink(3000 + Math.random() * 1000);
  }, delay);
}

async function startApp() {
  if (runtime.started) return;
  if (runtime.ws && runtime.ws.readyState === WebSocket.OPEN) {
    runtime.ws.close();
    runtime.ws = null;
  }
  bootCopy.textContent = "カメラとマイクを有効化しています。";
  bootNote.textContent = "初回はブラウザの許可が必要です。";
  bootStartButton.disabled = true;
  try {
    await connectVoiceSocket();
    await initMedia();
    runtime.started = true;
    bootOverlay.classList.add("is-hidden");
    queueBlink(3000 + Math.random() * 1000);
    refreshVisualState();
    scheduleNextFrame(0);
  } catch (error) {
    runtime.bootBlocked = true;
    if (runtime.ws) {
      runtime.ws.close();
      runtime.ws = null;
    }
    bootCopy.textContent = "カメラまたはマイクの許可が必要です。";
    bootNote.textContent = String(error);
    bootStartButton.disabled = false;
  }
}

setInterval(updateClock, 10000);
updateClock();
applyState("idle");
refreshVisualState();
bootStartButton.addEventListener("click", startApp);
window.addEventListener("beforeunload", stopRuntime);
window.addEventListener("load", () => {
  startApp().catch(() => {
    bootStartButton.disabled = false;
  });
});
