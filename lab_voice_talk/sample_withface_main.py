import asyncio
import os
import re
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
_ORIGINAL_PROD_HANDLE_LLM_TTS = prod_base.handle_llm_tts

IS_SAMPLE_MODE = True
MODE_NAME = "sample"
NEXT_AUDIO_IS_REGISTRATION = False

_SCRIPT_PIPELINE_LOCK = asyncio.Lock()
SAMPLE_SKIP_INITIAL_AI = os.getenv("SAMPLE_WITHFACE_SKIP_INITIAL_AI", "1") == "1"

INLINE_SCRIPT_TURNS: List[Dict[str, str]] = [
    {"role": "ai", "text": "おはようございます、田中さん。本人確認が完了しました。出勤を記録しました。"},
    {"role": "human", "text": "おはよう。"},
    {"role": "ai", "text": "本日の予定と重要事項をまとめてお知らせします。"},
    {"role": "ai", "text": "本日は、9時に営業定例、11時にA社との商談、14時に社内レビュー、17時に日報の締切があります。優先度が高いのは11時のA社商談です。準備状況は60パーセントです。"},
    {"role": "human", "text": "まだ足りないね。"},
    {"role": "ai", "text": "不足しているポイントを整理します。A社はコスト削減と短期導入を重視しています。前回は価格面で保留となっています。"},
    {"role": "human", "text": "価格がポイントか。"},
    {"role": "ai", "text": "はい。想定される質問と回答案をお伝えします。"},
    {"role": "ai", "text": "想定される質問は、価格をどこまで下げられるかという点です。回答案としては、段階的な導入によって初期コストを抑える提案が有効です。"},
    {"role": "ai", "text": "田中さん、昨日は20時まで勤務しています。本日は負荷軽減のため、14時の会議を短縮することを提案します。"},
    {"role": "human", "text": "いいね、やろう。"},
    {"role": "ai", "text": "関係者へ15分短縮の打診を送信しました。"},
    {"role": "ai", "text": "A社から返信がありました。本日の商談で価格調整について相談したいとのことです。"},
    {"role": "human", "text": "想定通りだね。"},
    {"role": "ai", "text": "価格調整の提案パターンを準備しました。"},
    {"role": "ai", "text": "初期費用を抑えて月額で回収する案があります。機能を段階的に導入する案もあります。長期契約によって割引を行う案もあります。"},
    {"role": "ai", "text": "本日の重要ポイントは三つです。A社商談での価格対応。会議時間の最適化。日報締切の遵守です。"},
    {"role": "ai", "text": "本日も業務を最適化します。いつでも話しかけてください。"},
    {"role": "human", "text": "助かるよ。"},
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


SCRIPT_TURNS = INLINE_SCRIPT_TURNS
_ai_count = sum(1 for turn in SCRIPT_TURNS if turn["role"] == "ai")
_human_count = sum(1 for turn in SCRIPT_TURNS if turn["role"] == "human")
logger.info("[SAMPLE_SCRIPT] loaded turns=%d source=inline", len(SCRIPT_TURNS))
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
        await _ORIGINAL_PROD_HANDLE_LLM_TTS(answer_text, websocket, history)
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
