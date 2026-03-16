const screenEl = document.querySelector(".phone-screen");
const stateButtons = [...document.querySelectorAll("[data-set-state]")];
const directorPanel = document.querySelector(".director-panel");
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
const runDemoButton = document.getElementById("run-demo");
const toggleOverlayButton = document.getElementById("toggle-overlay");
const assistantFace = document.getElementById("assistant-face");

const STATES = {
  idle: {
    pill: "IDLE",
    title: "待機中",
    subtitle: "人が近づくと検知を開始します。",
    orbit: "STANDBY",
    badge: "No Target",
    target: "未検知",
    identity: "Unknown",
    mode: "Standby",
    user: "......",
    ai: "受付の準備ができています。",
    dialogue: "Waiting",
  },
  detecting: {
    pill: "SCAN",
    title: "人物を検知しました",
    subtitle: "スマホが前方の人物を追跡しています。",
    orbit: "TRACKING",
    badge: "Human Detected",
    target: "1 Person",
    identity: "Analyzing...",
    mode: "Person Detection",
    user: "……",
    ai: "人物を確認中です。",
    dialogue: "Tracking",
  },
  recognized: {
    pill: "MATCH",
    title: "顔認識に成功",
    subtitle: "社員データベースと照合しています。",
    orbit: "IDENTITY LOCK",
    badge: "Face Recognized",
    target: "Face Locked",
    identity: "Okada Hiroaki",
    mode: "Face Recognition",
    user: "……",
    ai: "こんにちは。岡田さん。",
    dialogue: "Matched",
  },
  listening: {
    pill: "LISTEN",
    title: "AIが聞いています",
    subtitle: "用件を音声で受け付けています。",
    orbit: "LISTENING",
    badge: "Mic Active",
    target: "Speaking User",
    identity: "Okada Hiroaki",
    mode: "Speech Input",
    user: "会議室を予約したいです。",
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
    identity: "Okada Hiroaki",
    mode: "Response Planning",
    user: "会議室を予約したいです。",
    ai: "少々お待ちください。最適な案内を準備しています。",
    dialogue: "Thinking",
  },
  speaking: {
    pill: "SPEAK",
    title: "AIが話しています",
    subtitle: "案内内容を音声で返答しています。",
    orbit: "VOICE OUT",
    badge: "Voice Reply",
    target: "Engaged",
    identity: "Okada Hiroaki",
    mode: "Speech Output",
    user: "会議室を予約したいです。",
    ai: "本日 14 時から第 3 会議室をご利用いただけます。",
    dialogue: "Speaking",
  },
  farewell: {
    pill: "BYE",
    title: "見送りモード",
    subtitle: "会話が終了し、再び待機に戻ります。",
    orbit: "SESSION END",
    badge: "Leaving",
    target: "Exit Detected",
    identity: "Okada Hiroaki",
    mode: "Farewell",
    user: "ありがとうございます。",
    ai: "ありがとうございました。お気をつけて。",
    dialogue: "Farewell",
  },
};

let demoTimerIds = [];
let blinkTimerId = null;

function clearDemoTimers() {
  for (const id of demoTimerIds) {
    clearTimeout(id);
  }
  demoTimerIds = [];
}

function setActiveButton(state) {
  for (const button of stateButtons) {
    button.classList.toggle("is-active", button.dataset.setState === state);
  }
}

function applyState(state) {
  const config = STATES[state];
  if (!config) return;
  screenEl.dataset.state = state;
  heroTitle.textContent = config.title;
  heroSubtitle.textContent = config.subtitle;
  statePill.textContent = config.pill;
  orbitText.textContent = config.orbit;
  feedBadge.textContent = config.badge;
  targetLabel.textContent = config.badge.toLowerCase();
  metaTarget.textContent = config.target;
  metaIdentity.textContent = config.identity;
  metaMode.textContent = config.mode;
  bubbleUser.textContent = config.user;
  bubbleAi.textContent = config.ai;
  dialogueStage.textContent = config.dialogue;
  setActiveButton(state);
}

function scheduleDemo() {
  clearDemoTimers();
  const sequence = [
    ["idle", 0],
    ["detecting", 1200],
    ["recognized", 2600],
    ["listening", 4300],
    ["thinking", 6200],
    ["speaking", 8000],
    ["farewell", 11200],
    ["idle", 13600],
  ];
  for (const [state, delay] of sequence) {
    demoTimerIds.push(window.setTimeout(() => applyState(state), delay));
  }
}

function queueBlink(delay) {
  if (blinkTimerId) clearTimeout(blinkTimerId);
  blinkTimerId = window.setTimeout(() => {
    assistantFace.classList.add("is-blinking");
    window.setTimeout(() => assistantFace.classList.remove("is-blinking"), 140);
    const nextDelay = 3000 + Math.random() * 1000;
    queueBlink(nextDelay);
  }, delay);
}

for (const button of stateButtons) {
  button.addEventListener("click", () => {
    clearDemoTimers();
    applyState(button.dataset.setState);
  });
}

runDemoButton.addEventListener("click", scheduleDemo);

toggleOverlayButton.addEventListener("click", () => {
  directorPanel.classList.toggle("is-hidden");
  toggleOverlayButton.textContent = directorPanel.classList.contains("is-hidden")
    ? "操作を表示"
    : "操作を隠す";
});

window.addEventListener("keydown", (event) => {
  const keyMap = {
    "1": "idle",
    "2": "detecting",
    "3": "recognized",
    "4": "listening",
    "5": "thinking",
    "6": "speaking",
    "7": "farewell",
  };
  if (keyMap[event.key]) {
    clearDemoTimers();
    applyState(keyMap[event.key]);
  }
  if (event.key.toLowerCase() === "d") {
    scheduleDemo();
  }
});

applyState("idle");
queueBlink(3000 + Math.random() * 1000);
