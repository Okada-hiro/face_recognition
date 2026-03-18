import asyncio
import os
import re
import subprocess
from typing import Dict, List

import parallel_faster_main as prod_base


logger = prod_base.logger
DEVICE = prod_base.DEVICE
PROCESSING_DIR = prod_base.PROCESSING_DIR
GLOBAL_ASR_MODEL_INSTANCE = prod_base.GLOBAL_ASR_MODEL_INSTANCE
tts_module = prod_base.tts_module
speaker_guard = prod_base.speaker_guard
vad_model = prod_base.vad_model
VADIterator = prod_base.VADIterator
get_root = prod_base.get_root
os = prod_base.os
synthesize_speech = prod_base.synthesize_speech
synthesize_speech_to_memory = prod_base.synthesize_speech_to_memory
synthesize_speech_to_memory_stream = prod_base.synthesize_speech_to_memory_stream
synthesize_speech_to_memory_for_worker = prod_base.synthesize_speech_to_memory_for_worker
synthesize_speech_to_memory_stream_for_worker = prod_base.synthesize_speech_to_memory_stream_for_worker

IS_SAMPLE_MODE = True
MODE_NAME = "sample"
NEXT_AUDIO_IS_REGISTRATION = False

_SCRIPT_PIPELINE_LOCK = asyncio.Lock()
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SAMPLE_SCRIPT_PATH = os.getenv("SAMPLE_SCRIPT_PATH", os.path.join(_REPO_ROOT, "原稿案.rtf"))
SAMPLE_SCRIPT_SOURCE = os.getenv("SAMPLE_SCRIPT_SOURCE", "auto").strip().lower()
SAMPLE_SKIP_INITIAL_AI = os.getenv("SAMPLE_WITHFACE_SKIP_INITIAL_AI", "1") == "1"

INLINE_SCRIPT_TURNS: List[Dict[str, str]] = [
    {"role": "ai", "text": "本日の予定と重要事項をまとめてお知らせします。"},
    {"role": "human", "text": "まだ足りないね。"},
    {"role": "ai", "text": "不足しているポイントを整理します。A社はコスト削減と短期導入を重視しています。"},
]


def set_next_audio_is_registration(enabled: bool) -> None:
    global NEXT_AUDIO_IS_REGISTRATION
    NEXT_AUDIO_IS_REGISTRATION = enabled
    prod_base.NEXT_AUDIO_IS_REGISTRATION = enabled


def get_next_audio_is_registration() -> bool:
    return bool(getattr(prod_base, "NEXT_AUDIO_IS_REGISTRATION", NEXT_AUDIO_IS_REGISTRATION))


def create_session_state() -> dict:
    cursor = 0
    skipped_ai = 0
    if SAMPLE_SKIP_INITIAL_AI:
        while cursor < len(SCRIPT_TURNS) and SCRIPT_TURNS[cursor]["role"] == "ai":
            cursor += 1
            skipped_ai += 1
    if skipped_ai:
        logger.info("[SAMPLE_SCRIPT] skipped_leading_ai_turns=%d", skipped_ai)
    return {"cursor": cursor, "chat_history": []}


def _decode_rtf_unicode(raw: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        num = int(match.group(1))
        if num < 0:
            num += 65536
        try:
            return chr(num)
        except ValueError:
            return ""

    return re.sub(r"\\u(-?\d+)\??", _repl, raw)


def _rtf_to_plain_text(raw: str) -> str:
    text = raw.replace("\\\n", "\n")
    text = _decode_rtf_unicode(text)
    text = re.sub(r"\\'[0-9a-fA-F]{2}", "", text)
    text = re.sub(r"\\[a-zA-Z*]+-?\d* ?", "", text)
    text = text.replace("{", "").replace("}", "")
    text = text.replace("\\", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _rtf_to_plain_text_via_textutil(path: str) -> str:
    try:
        proc = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", path],
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()
    except Exception:
        return ""


def _cleanup_script_text(text: str) -> str:
    cleaned = (text or "").replace("\u3000", " ").strip()
    cleaned = re.sub(
        r"(?<=[\u3040-\u30ff\u3400-\u9fffA-Za-z0-9])\s+(?=[\u3040-\u30ff\u3400-\u9fffA-Za-z0-9])",
        "",
        cleaned,
    )
    cleaned = re.sub(r"\s+([。、，,.！？!?\)])", r"\1", cleaned)
    cleaned = re.sub(r"([\(\[「『])\s+", r"\1", cleaned)
    cleaned = cleaned.strip("「」『』\"'")
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def _load_script_plain_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        raw = f.read()
    if path.lower().endswith(".rtf"):
        return _rtf_to_plain_text_via_textutil(path) or _rtf_to_plain_text(raw)
    return raw


def _parse_script_turns(plain: str) -> List[Dict[str, str]]:
    turns: List[Dict[str, str]] = []
    current_role: str | None = None
    current_parts: List[str] = []
    role_map = {"AI": "ai", "人間": "human", "社員": "human", "田中": "human"}
    label_re = re.compile(r"^(AI|人間|社員|田中)\s*[:：]?\s*(.*)$")

    for raw_line in plain.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = label_re.match(line)
        if match:
            if current_role and current_parts:
                text = _cleanup_script_text("".join(current_parts))
                if text:
                    turns.append({"role": current_role, "text": text})
            current_role = role_map[match.group(1)]
            remainder = _cleanup_script_text(match.group(2))
            current_parts = [remainder] if remainder else []
            continue
        current_parts.append(line)

    if current_role and current_parts:
        text = _cleanup_script_text("".join(current_parts))
        if text:
            turns.append({"role": current_role, "text": text})
    return turns


def _load_sample_turns(path: str) -> List[Dict[str, str]]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"sample script not found: {path}")
    turns = _parse_script_turns(_load_script_plain_text(path))
    if not turns:
        raise ValueError("no script turns found in sample script")
    return turns


def _load_configured_script_turns() -> List[Dict[str, str]]:
    source = SAMPLE_SCRIPT_SOURCE
    if source == "inline":
        logger.info("[SAMPLE_SCRIPT] loaded turns=%d source=inline", len(INLINE_SCRIPT_TURNS))
        return INLINE_SCRIPT_TURNS
    if source == "file":
        turns = _load_sample_turns(SAMPLE_SCRIPT_PATH)
        logger.info("[SAMPLE_SCRIPT] loaded turns=%d source=file path=%s", len(turns), SAMPLE_SCRIPT_PATH)
        return turns
    if os.path.exists(SAMPLE_SCRIPT_PATH):
        turns = _load_sample_turns(SAMPLE_SCRIPT_PATH)
        logger.info("[SAMPLE_SCRIPT] loaded turns=%d source=auto path=%s", len(turns), SAMPLE_SCRIPT_PATH)
        return turns
    logger.warning("[SAMPLE_SCRIPT] path not found -> falling back to inline path=%s", SAMPLE_SCRIPT_PATH)
    return INLINE_SCRIPT_TURNS


SCRIPT_TURNS = _load_configured_script_turns()
_ai_count = sum(1 for turn in SCRIPT_TURNS if turn["role"] == "ai")
_human_count = sum(1 for turn in SCRIPT_TURNS if turn["role"] == "human")
logger.info("[SAMPLE_SCRIPT] role_counts ai=%d human=%d", _ai_count, _human_count)
if SCRIPT_TURNS:
    logger.info(
        "[SAMPLE_SCRIPT] first_turn role=%s len=%d text=%r",
        SCRIPT_TURNS[0]["role"],
        len(SCRIPT_TURNS[0]["text"]),
        SCRIPT_TURNS[0]["text"][:80],
    )


def _normalize_for_compare(text: str) -> str:
    normalized = text.strip()
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"[。、，,.！？!?\-ー「」『』（）()]", "", normalized)
    return normalized


def _extract_user_text(text_with_context: str) -> str:
    match = re.match(r"^【[^】]+】\s*(.*)$", text_with_context)
    return match.group(1).strip() if match else text_with_context.strip()


def _consume_ai_block(state: dict) -> str:
    idx = state["cursor"]
    while idx < len(SCRIPT_TURNS) and SCRIPT_TURNS[idx]["role"] != "ai":
        idx += 1
    if idx >= len(SCRIPT_TURNS):
        state["cursor"] = idx
        return ""
    state["cursor"] = idx + 1
    return SCRIPT_TURNS[idx]["text"].strip()


def _consume_human_then_ai(state: dict, user_text: str) -> str:
    idx = state["cursor"]
    while idx < len(SCRIPT_TURNS) and SCRIPT_TURNS[idx]["role"] == "ai":
        idx += 1
    if idx < len(SCRIPT_TURNS) and SCRIPT_TURNS[idx]["role"] == "human":
        expected = SCRIPT_TURNS[idx]["text"]
        ok = _normalize_for_compare(expected) == _normalize_for_compare(user_text)
        logger.info(
            "[SAMPLE_SCRIPT] human_match=%s idx=%d expected=%r got=%r",
            ok,
            idx + 1,
            expected,
            user_text,
        )
        idx += 1
    state["cursor"] = idx
    return _consume_ai_block(state)


def _iter_answer_chunks(answer_text: str):
    chunk_size = max(1, int(os.getenv("SAMPLE_STREAM_CHARS", "12")))
    for index in range(0, len(answer_text), chunk_size):
        yield answer_text[index : index + chunk_size]


async def handle_llm_tts(answer_text: str, websocket, chat_history: list | None = None):
    history = chat_history if chat_history is not None else []
    original_stream = prod_base.generate_answer_stream

    def _fixed_stream(_text_for_llm: str, history=None):
        return _iter_answer_chunks(answer_text)

    prod_base.generate_answer_stream = _fixed_stream
    try:
        await prod_base.handle_llm_tts(answer_text, websocket, history)
    finally:
        prod_base.generate_answer_stream = original_stream


async def process_voice_pipeline(audio_float32_np, websocket, session_state: dict):
    state = session_state or create_session_state()
    chat_history = state.setdefault("chat_history", [])

    async def _scripted_handle(text_for_llm: str, websocket_inner, _chat_history):
        user_text = _extract_user_text(text_for_llm)
        fixed_reply = _consume_human_then_ai(state, user_text)
        if not fixed_reply:
            logger.info("[SAMPLE_SCRIPT] no more AI lines to speak (scenario finished)")
            await websocket_inner.send_json({"status": "complete", "answer_text": ""})
            return
        await handle_llm_tts(fixed_reply, websocket_inner, chat_history)

    original_handle = prod_base.handle_llm_tts
    async with _SCRIPT_PIPELINE_LOCK:
        prod_base.NEXT_AUDIO_IS_REGISTRATION = NEXT_AUDIO_IS_REGISTRATION
        prod_base.handle_llm_tts = _scripted_handle
        try:
            await prod_base.process_voice_pipeline(audio_float32_np, websocket, chat_history)
        finally:
            set_next_audio_is_registration(bool(getattr(prod_base, "NEXT_AUDIO_IS_REGISTRATION", False)))
            prod_base.handle_llm_tts = original_handle
