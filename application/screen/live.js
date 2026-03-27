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
const dialogueNote = document.getElementById("dialogue-note");
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
const RECEPTION_CONFIG = window.RECEPTION_CONFIG || {};
const DEFAULT_WS_PROTOCOL = window.location.protocol === "https:" ? "wss://" : "ws://";
const DEFAULT_VOICE_WS_URL = `${DEFAULT_WS_PROTOCOL}${window.location.host}/ws`;
const RUNPOD_PROXY_RE = /^(.*)-(\d+)\.proxy\.runpod\.net$/;
let CONFIG_ERROR = "";

function deriveProxyOrigin(targetPort) {
  const { protocol, hostname, host, port } = window.location;
  const match = hostname.match(RUNPOD_PROXY_RE);
  if (match) {
    return `${protocol}//${match[1]}-${targetPort}.proxy.runpod.net`;
  }
  if (port) {
    return `${protocol}//${hostname}:${targetPort}`;
  }
  return `${protocol}//${host}`;
}

function normalizeVisionHttpBase(value) {
  const raw = String(value || "").trim();
  let candidate = "";
  if (!raw) {
    candidate = deriveProxyOrigin(8000);
  } else if (raw.startsWith("/")) {
    candidate = `${window.location.origin}${raw}`.replace(/\/$/, "");
  } else {
    candidate = raw.replace(/\/$/, "");
  }
  let parsed;
  try {
    parsed = new URL(candidate);
  } catch (error) {
    throw new Error(`Invalid vision URL: ${candidate} (${error})`);
  }
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error(`Invalid vision URL protocol: ${candidate}`);
  }
  return parsed.toString().replace(/\/$/, "");
}

function normalizeVoiceWsUrl(value) {
  const raw = String(value || "").trim();
  let candidate = "";
  if (!raw) {
    candidate = `${DEFAULT_WS_PROTOCOL}${window.location.host}/voice-ws`;
  } else if (raw.startsWith("/")) {
    candidate = `${DEFAULT_WS_PROTOCOL}${window.location.host}${raw}`;
  } else if (raw.startsWith("https://")) {
    candidate = `wss://${raw.slice("https://".length)}`;
  } else if (raw.startsWith("http://")) {
    candidate = `ws://${raw.slice("http://".length)}`;
  } else if (/^[A-Za-z0-9.-]+(?::\d+)?\/.*$/.test(raw)) {
    candidate = `${DEFAULT_WS_PROTOCOL}${raw}`;
  } else {
    candidate = raw;
  }
  let parsed;
  try {
    parsed = new URL(candidate);
  } catch (error) {
    throw new Error(`Invalid voice WS URL: ${candidate} (${error})`);
  }
  if (!["ws:", "wss:"].includes(parsed.protocol)) {
    throw new Error(`Invalid voice WS URL protocol: ${candidate}`);
  }
  return parsed.toString();
}

let VISION_HTTP_BASE = "";
let VOICE_WS_URL = "";
try {
  VISION_HTTP_BASE = normalizeVisionHttpBase(RECEPTION_CONFIG.visionHttpBase);
  VOICE_WS_URL = normalizeVoiceWsUrl(RECEPTION_CONFIG.voiceWsUrl);
} catch (error) {
  CONFIG_ERROR = String(error);
  console.error("[RECEPTION_CONFIG_ERROR]", error, RECEPTION_CONFIG);
}

const STATES = {
  idle: {
    pill: "待機",
    title: "待機中",
    subtitle: "人が近づくと顔認識と会話を開始します。",
    orbit: "待機中",
    badge: "対象なし",
    target: "未検知",
    identity: "未認識",
    mode: "待機中",
    user: "……",
    ai: "受付の準備ができています。",
    dialogue: "待機中",
  },
  detecting: {
    pill: "検知",
    title: "人物を検知しました",
    subtitle: "前方の人物を追跡しています。",
    orbit: "追跡中",
    badge: "人物検知",
    target: "人物を追跡中",
    identity: "照合中…",
    mode: "人物検知",
    user: "……",
    ai: "人物を確認しています。",
    dialogue: "追跡中",
  },
  recognized: {
    pill: "一致",
    title: "顔認識に成功",
    subtitle: "社員データベースとの照合が完了しました。",
    orbit: "照合完了",
    badge: "顔を認識",
    target: "対象を特定",
    identity: "認識済み",
    mode: "顔認識",
    user: "……",
    ai: "こんにちは。",
    dialogue: "認識完了",
  },
  listening: {
    pill: "傾聴",
    title: "AIが聞いています",
    subtitle: "用件を音声で受け付けています。",
    orbit: "音声受付",
    badge: "音声入力",
    target: "発話中",
    identity: "認識済み",
    mode: "音声入力",
    user: "……",
    ai: "……",
    dialogue: "聞き取り中",
  },
  thinking: {
    pill: "応答",
    title: "回答を考えています",
    subtitle: "音声と認識情報をもとに返答を生成しています。",
    orbit: "応答生成",
    badge: "処理中",
    target: "文脈を整理",
    identity: "認識済み",
    mode: "回答生成",
    user: "……",
    ai: "少々お待ちください。",
    dialogue: "考え中",
  },
  speaking: {
    pill: "発話",
    title: "AIが話しています",
    subtitle: "案内内容を音声で返答しています。",
    orbit: "音声案内",
    badge: "音声出力",
    target: "応対中",
    identity: "認識済み",
    mode: "音声出力",
    user: "……",
    ai: "案内を開始します。",
    dialogue: "発話中",
  },
  farewell: {
    pill: "終了",
    title: "見送りモード",
    subtitle: "会話を終えて待機に戻ります。",
    orbit: "終了処理",
    badge: "離脱検知",
    target: "退出を検知",
    identity: "認識済み",
    mode: "見送り",
    user: "ありがとうございました。",
    ai: "ありがとうございました。お気をつけて。",
    dialogue: "見送り",
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
  latestTargetCenterX: 0.5,
  latestTargetCenterY: 0.42,
  latestUserText: "……",
  latestAiText: "受付の準備ができています。",
  currentAiBubbleText: "",
  currentIdentity: "未認識",
  currentMode: "待機中",
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
  lastFeedObjectUrl: null,
  jitterPrimed: false,
  pendingGreeting: false,
  pendingGreetingSinceMs: 0,
  unknownFaceFrames: 0,
  faceResultSent: false,
  wsRttMs: null,
  lastFrameRttMs: null,
  audioCaptureAnnounced: false,
};

function updateEyeGaze(centerX = 0.5, centerY = 0.42) {
  if (!assistantFace) return;
  const normalizedX = Math.max(0, Math.min(1, Number.isFinite(centerX) ? centerX : 0.5));
  const normalizedY = Math.max(0, Math.min(1, Number.isFinite(centerY) ? centerY : 0.42));
  const offsetX = (normalizedX - 0.5) * 22;
  const offsetY = (normalizedY - 0.42) * 12;
  assistantFace.style.setProperty("--eye-offset-x", `${offsetX.toFixed(1)}px`);
  assistantFace.style.setProperty("--eye-offset-y", `${offsetY.toFixed(1)}px`);
}

function showDialogueNote(message) {
  if (!dialogueNote) return;
  const text = String(message || "").trim();
  if (!text) {
    dialogueNote.hidden = true;
    dialogueNote.textContent = "";
    return;
  }
  dialogueNote.hidden = false;
  dialogueNote.textContent = text;
}

function sendRecognitionEvent(eventName, personId = null) {
  if (!runtime.ws || runtime.ws.readyState !== WebSocket.OPEN) return;
  runtime.ws.send(JSON.stringify({
    type: "recognition_event",
    event: eventName,
    person_id: personId,
  }));
}

function handleTrackEvents(trackEvents) {
  for (const item of trackEvents) {
    if (!item || !item.event_type) continue;
    if (item.event_type === "approached") {
      sendRecognitionEvent("approach", item.person_id || null);
      runtime.pendingGreeting = true;
      runtime.pendingGreetingSinceMs = performance.now();
      runtime.faceResultSent = false;
      runtime.unknownFaceFrames = 0;
    } else if (item.event_type === "left") {
      sendRecognitionEvent("leave", item.person_id || null);
      runtime.pendingGreeting = false;
      runtime.pendingGreetingSinceMs = 0;
      runtime.faceResultSent = false;
      runtime.unknownFaceFrames = 0;
      if (!item.person_id || item.person_id === runtime.recognizedPersonId) {
        runtime.recognizedPersonId = null;
      }
    }
  }
}

function updateGreetingDecision(primaryPersonId, faceCount, matchCount) {
  if (runtime.faceResultSent) return;
  const pendingMs = runtime.pendingGreetingSinceMs ? performance.now() - runtime.pendingGreetingSinceMs : 0;
  if (primaryPersonId) {
    runtime.recognizedPersonId = primaryPersonId;
    sendRecognitionEvent("recognized_face", primaryPersonId);
    runtime.pendingGreeting = false;
    runtime.pendingGreetingSinceMs = 0;
    runtime.faceResultSent = true;
    runtime.unknownFaceFrames = 0;
    return;
  }
  if (faceCount > 0 && matchCount === 0) {
    runtime.unknownFaceFrames += 1;
    if (runtime.unknownFaceFrames >= 3) {
      sendRecognitionEvent("unknown_face", null);
      runtime.pendingGreeting = false;
      runtime.pendingGreetingSinceMs = 0;
      runtime.faceResultSent = true;
      runtime.unknownFaceFrames = 0;
    }
    return;
  }
  if (runtime.pendingGreeting && runtime.latestPersonCount > 0 && pendingMs >= 2500) {
    sendRecognitionEvent("unknown_face", null);
    runtime.pendingGreeting = false;
    runtime.pendingGreetingSinceMs = 0;
    runtime.faceResultSent = true;
    runtime.unknownFaceFrames = 0;
    return;
  }
  if (faceCount <= 0) {
    runtime.unknownFaceFrames = 0;
  }
}

function updateClock() {
  const now = new Date();
  statusTime.textContent = now.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function updateViewportMetrics() {
  const viewport = window.visualViewport;
  const viewportWidth = Math.max(320, Math.round(viewport?.width || window.innerWidth || 0));
  const viewportHeight = Math.max(560, Math.round(viewport?.height || window.innerHeight || 0));
  const phoneRatio = clamp(viewportWidth / viewportHeight, 0.5, 0.6);
  const availableWidth = Math.max(300, viewportWidth - 12);
  const availableHeight = Math.max(520, viewportHeight - 12);
  const widthByHeight = availableHeight * phoneRatio;
  const phoneWidth = clamp(Math.min(availableWidth, widthByHeight, 468), 300, 468);
  const root = document.documentElement;
  root.style.setProperty("--phone-frame-width", `${phoneWidth.toFixed(1)}px`);
  root.style.setProperty("--phone-frame-ratio", `${phoneRatio.toFixed(4)}`);
  root.style.setProperty("--live-stage-pad-top", `max(8px, env(safe-area-inset-top, 0px))`);
  root.style.setProperty("--live-stage-pad-right", `max(8px, env(safe-area-inset-right, 0px))`);
  root.style.setProperty("--live-stage-pad-bottom", `max(8px, env(safe-area-inset-bottom, 0px))`);
  root.style.setProperty("--live-stage-pad-left", `max(8px, env(safe-area-inset-left, 0px))`);
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
  const identity = runtime.recognizedPersonId || (runtime.latestFaceCount > 0 ? "来訪者" : "未認識");
  const target =
    runtime.latestFaceCount > 0
      ? "顔を検出"
      : runtime.latestPersonCount > 0
        ? `${runtime.latestPersonCount}人を検知`
        : "未検知";
  const mode =
    state === "speaking"
      ? "音声出力"
      : state === "thinking"
        ? "回答生成"
        : state === "listening"
          ? "音声入力"
          : state === "recognized"
            ? "顔認識"
            : state === "detecting"
              ? "人物検知"
              : "待機中";
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
  const frameRtt = runtime.lastFrameRttMs == null ? "-" : `${Math.round(runtime.lastFrameRttMs)}ms`;
  const wsRtt = runtime.wsRttMs == null ? "-" : `${Math.round(runtime.wsRttMs)}ms`;
  debugPill.textContent = `人物 ${runtime.latestPersonCount} / 顔 ${runtime.latestFaceCount} | ${dialogueStage.textContent} | 映像 ${frameRtt} | 音声 ${wsRtt}`;
  updateEyeGaze(runtime.latestTargetCenterX, runtime.latestTargetCenterY);
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
  const socket = new WebSocket(VOICE_WS_URL || DEFAULT_VOICE_WS_URL);
  socket.binaryType = "arraybuffer";

  socket.onopen = () => {
    netPill.textContent = "接続中";
    runtime.ws = socket;
    socket.send(JSON.stringify({
      type: "diag_ping",
      client_sent_ms: Date.now(),
    }));
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
    if (data.status === "diag_pong") {
      if (typeof data.client_sent_ms === "number") {
      runtime.wsRttMs = Date.now() - data.client_sent_ms;
        refreshVisualState();
      }
    } else if (data.status === "system_info") {
      runtime.latestAiText = data.message;
      runtime.currentAiBubbleText = "";
      if (data.message.includes("接近")) {
        runtime.recognizedPersonId = runtime.recognizedPersonId || runtime.currentIdentity;
      }
      showDialogueNote("");
    } else if (data.status === "processing") {
      runtime.listening = data.message.includes("聞いています");
      runtime.thinking = data.message.includes("思考中");
      if (runtime.thinking) runtime.listening = false;
      showDialogueNote("");
    } else if (data.status === "transcribed") {
      runtime.latestUserText = data.question_text || "……";
      runtime.listening = false;
      runtime.thinking = true;
      showDialogueNote("");
    } else if (data.status === "reply_chunk") {
      runtime.speaking = true;
      runtime.thinking = false;
      runtime.currentAiBubbleText += data.text_chunk || "";
      runtime.latestAiText = runtime.currentAiBubbleText;
      showDialogueNote("");
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
      showDialogueNote("");
    } else if (data.status === "interrupt") {
      stopAudioPlayback();
      runtime.speaking = false;
    } else if (data.status === "ignored") {
      runtime.listening = false;
      runtime.thinking = false;
      showDialogueNote(data.message || "会話が短すぎます。");
    } else if (data.status === "system_alert") {
      runtime.listening = false;
      runtime.thinking = false;
      showDialogueNote(data.message || "");
    } else if (data.status === "error") {
      showDialogueNote(data.message || "処理エラー");
    }
    refreshVisualState();
  };

  socket.onclose = () => {
    runtime.ws = null;
    netPill.textContent = "再接続";
    showDialogueNote("音声接続が切れました。");
  };

  socket.onerror = () => {
    netPill.textContent = "通信エラー";
    showDialogueNote("音声接続エラー");
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
    if (!runtime.audioCaptureAnnounced) {
      runtime.audioCaptureAnnounced = true;
      runtime.ws.send(JSON.stringify({
        type: "client_audio_capture_started",
        client_sent_ms: Date.now(),
      }));
    }
    runtime.ws.send(event.inputBuffer.getChannelData(0).buffer);
  };
  runtime.sourceInput.connect(runtime.processor);
  runtime.processor.connect(runtime.audioContext.destination);
  if (runtime.audioContext.state === "suspended") {
    await runtime.audioContext.resume();
  }
}

async function captureAndSendFrame() {
  if (!runtime.stream || runtime.busyFrame || !cameraVideo.videoWidth) return;
  runtime.busyFrame = true;
  try {
    const frameRequestStart = performance.now();
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
    const response = await fetch(`${VISION_HTTP_BASE}/api/live-frame`, { method: "POST", body: form });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    const imageBlob = await response.blob();
    const nextFeedObjectUrl = URL.createObjectURL(imageBlob);
    feedImage.src = nextFeedObjectUrl;
    if (runtime.lastFeedObjectUrl) {
      URL.revokeObjectURL(runtime.lastFeedObjectUrl);
    }
    runtime.lastFeedObjectUrl = nextFeedObjectUrl;
    runtime.frameCount += 1;
    const matchCount = Number(response.headers.get("x-match-count") || "0");
    runtime.latestPersonCount = Number(response.headers.get("x-person-count") || "0");
    runtime.latestFaceCount = Number(response.headers.get("x-face-count") || "0");
    runtime.latestTargetCenterX = Number(response.headers.get("x-primary-person-cx") || "0.5");
    runtime.latestTargetCenterY = Number(response.headers.get("x-primary-person-cy") || "0.42");
    const primaryPersonIdRaw = response.headers.get("x-primary-person-id") || "";
    const primaryPersonId = primaryPersonIdRaw ? decodeURIComponent(primaryPersonIdRaw) : "";
    runtime.recognizedPersonId = primaryPersonId || runtime.recognizedPersonId;
    runtime.latestTrackEvents = JSON.parse(response.headers.get("x-track-events") || "[]");
    handleTrackEvents(runtime.latestTrackEvents);
    updateGreetingDecision(primaryPersonId, runtime.latestFaceCount, matchCount);
    runtime.lastFrameRttMs = performance.now() - frameRequestStart;
    runtime.latestIntervalMs = computeNextInterval(runtime.latestPersonCount, runtime.latestFaceCount);
    runtime.currentIdentity = runtime.recognizedPersonId || (runtime.latestFaceCount > 0 ? "来訪者" : "未認識");
    runtime.currentTarget =
      runtime.latestFaceCount > 0
        ? "顔を検出"
        : runtime.latestPersonCount > 0
          ? `${runtime.latestPersonCount}人を検知`
          : "未検知";
    if (!runtime.latestPersonCount && !runtime.latestFaceCount && !runtime.speaking && !runtime.thinking && !runtime.listening) {
      runtime.recognizedPersonId = null;
      runtime.pendingGreeting = false;
      runtime.pendingGreetingSinceMs = 0;
      runtime.faceResultSent = false;
      runtime.unknownFaceFrames = 0;
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
  if (runtime.lastFeedObjectUrl) {
    URL.revokeObjectURL(runtime.lastFeedObjectUrl);
    runtime.lastFeedObjectUrl = null;
  }
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
  if (CONFIG_ERROR) {
    bootCopy.textContent = "接続先設定が不正です。";
    bootNote.textContent = CONFIG_ERROR;
    bootStartButton.disabled = false;
    return;
  }
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
    if (runtime.audioContext && runtime.audioContext.state === "suspended") {
      await runtime.audioContext.resume();
    }
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
updateViewportMetrics();
applyState("idle");
updateEyeGaze(0.5, 0.42);
refreshVisualState();
bootStartButton.addEventListener("click", startApp);
window.addEventListener("beforeunload", stopRuntime);
window.addEventListener("resize", updateViewportMetrics);
window.visualViewport?.addEventListener("resize", updateViewportMetrics);
window.visualViewport?.addEventListener("scroll", updateViewportMetrics);
window.addEventListener("load", () => {
  updateViewportMetrics();
  if (CONFIG_ERROR) {
    bootCopy.textContent = "接続先設定を確認してください。";
    bootNote.textContent = `${CONFIG_ERROR} | vision=${String(RECEPTION_CONFIG.visionHttpBase || "")} | voice=${String(RECEPTION_CONFIG.voiceWsUrl || "")}`;
    bootStartButton.disabled = false;
    return;
  }
  bootCopy.textContent = "開始ボタンを押してカメラとマイクを有効化してください。";
  bootNote.textContent = "音声再生を確実に有効化するため、最初の起動は手動で行います。";
  bootStartButton.disabled = false;
});
