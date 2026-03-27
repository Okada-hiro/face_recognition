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
    pill: "待機",
    title: "待機中",
    subtitle: "人が近づくと検知を開始します。",
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
    subtitle: "スマホが前方の人物を追跡しています。",
    orbit: "追跡中",
    badge: "人物検知",
    target: "人物を追跡中",
    identity: "照合中…",
    mode: "人物検知",
    user: "……",
    ai: "人物を確認中です。",
    dialogue: "追跡中",
  },
  recognized: {
    pill: "一致",
    title: "顔認識に成功",
    subtitle: "社員データベースと照合しています。",
    orbit: "照合完了",
    badge: "顔を認識",
    target: "対象を特定",
    identity: "Okada Hiroaki",
    mode: "顔認識",
    user: "……",
    ai: "こんにちは。岡田さん。",
    dialogue: "認識完了",
  },
  listening: {
    pill: "傾聴",
    title: "AIが聞いています",
    subtitle: "用件を音声で受け付けています。",
    orbit: "音声受付",
    badge: "音声入力",
    target: "発話中",
    identity: "Okada Hiroaki",
    mode: "音声入力",
    user: "会議室を予約したいです。",
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
    identity: "Okada Hiroaki",
    mode: "回答生成",
    user: "会議室を予約したいです。",
    ai: "少々お待ちください。最適な案内を準備しています。",
    dialogue: "考え中",
  },
  speaking: {
    pill: "発話",
    title: "AIが話しています",
    subtitle: "案内内容を音声で返答しています。",
    orbit: "音声案内",
    badge: "音声出力",
    target: "応対中",
    identity: "Okada Hiroaki",
    mode: "音声出力",
    user: "会議室を予約したいです。",
    ai: "本日 14 時から第 3 会議室をご利用いただけます。",
    dialogue: "発話中",
  },
  farewell: {
    pill: "終了",
    title: "見送りモード",
    subtitle: "会話が終了し、再び待機に戻ります。",
    orbit: "終了処理",
    badge: "離脱検知",
    target: "退出を検知",
    identity: "Okada Hiroaki",
    mode: "見送り",
    user: "ありがとうございます。",
    ai: "ありがとうございました。お気をつけて。",
    dialogue: "見送り",
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
  targetLabel.textContent = config.badge;
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
