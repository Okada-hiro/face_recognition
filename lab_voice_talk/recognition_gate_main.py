import asyncio
import importlib
import json
import os
import re
import time
from dataclasses import dataclass, field

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

VOICE_APP_MODE = os.getenv("RECOGNITION_VOICE_APP_MODE", "prod").strip().lower()
BASE_MODULE_NAME = "sample_withface_main" if VOICE_APP_MODE == "sample" else "parallel_faster_main"
base = importlib.import_module(BASE_MODULE_NAME)
answer_module = importlib.import_module("new_answer_generator")


app = FastAPI()
PROCESSING_DIR = getattr(base, "PROCESSING_DIR", "incoming_audio")
TTS_DEBUG_WEB_DIR = getattr(base, "TTS_DEBUG_WEB_DIR", os.path.join(PROCESSING_DIR, "tts_debug"))
TTS_DEBUG_VIEWER_HTML = getattr(
    base,
    "TTS_DEBUG_VIEWER_HTML",
    os.path.join(os.path.dirname(__file__), "tts_debug_browser.html"),
)
os.makedirs(PROCESSING_DIR, exist_ok=True)
os.makedirs(TTS_DEBUG_WEB_DIR, exist_ok=True)
app.mount("/download", StaticFiles(directory=PROCESSING_DIR), name="download")


@dataclass
class ActivationState:
    active: bool = False
    person_id: str | None = None
    person_reading: str | None = None
    greeted: bool = False
    recognition_pending: bool = False


@dataclass
class NameGuidanceState:
    active: bool = False
    stage: str = "idle"
    candidate_name: str | None = None
    candidate_reading: str | None = None
    turn_count: int = 0
    history: list[dict] = field(default_factory=list)
    finalizing: bool = False
    finalizing_started_at: float = 0.0
    pending_commit_name: str | None = None
    pending_commit_reading: str | None = None


STATE = ActivationState()
NAME_GUIDANCE = NameGuidanceState()
STATE_LOCK = asyncio.Lock()
WS_CLIENTS: set[WebSocket] = set()
WS_CLIENTS_LOCK = asyncio.Lock()
GREETING_PCM_CACHE: dict[str, bytes] = {}
ENABLE_BARGE_IN = os.getenv("RECOGNITION_ENABLE_BARGE_IN", "1") == "1"
GREETING_TTS_WORKER_ID = int(os.getenv("RECOGNITION_GREETING_TTS_WORKER_ID", "0"))
SESSION_RESET_EPOCH = 0
DEFAULT_KNOWN_GREETING_TEMPLATE = (
    "おはようございます、{person_id}さん。"
    if getattr(base, "IS_SAMPLE_MODE", False)
    else "{person_id}さん、こんにちは。"
)
DEFAULT_UNKNOWN_GREETING_TEXT = "おはようございます。" if getattr(base, "IS_SAMPLE_MODE", False) else "こんにちは。"
KNOWN_GREETING_TEMPLATE = os.getenv("RECOGNITION_GREETING_KNOWN_TEMPLATE", DEFAULT_KNOWN_GREETING_TEMPLATE)
UNKNOWN_GREETING_TEXT = os.getenv("RECOGNITION_GREETING_UNKNOWN_TEXT", DEFAULT_UNKNOWN_GREETING_TEXT)
ENABLE_GUIDED_NAME_CAPTURE = os.getenv("RECOGNITION_ENABLE_GUIDED_NAME_CAPTURE", "0") == "1"
NAME_CAPTURE_UI_FIRST = os.getenv("RECOGNITION_NAME_CAPTURE_UI_FIRST", "1") == "1"
NAME_CAPTURE_MODEL = os.getenv(
    "RECOGNITION_NAME_CAPTURE_MODEL",
    getattr(answer_module, "DEFAULT_MODEL", "gemini-2.5-flash-lite"),
)
NAME_CAPTURE_SYSTEM_PROMPT = """
あなたは受付AIの「名前特定専用」モジュールです。
目的は、音声認識の誤変換を前提に、できるだけ少ないターンで来訪者のフルネームを確定することです。

必ず守ること:
- 出力はJSONのみ
- display_text は字幕表示用の文です。漢字フルネームを書いてよいです
- spoken_text は TTS 読み上げ用の文です。candidate_reading がある場合は、その名前部分を必ず読み仮名で書いてください
- spoken_text では candidate_name の漢字をそのまま読ませないでください
- 読み違い・漢字違い・誤変換を前提に推測してよい
- ただし確定前は必ず確認する
- 名前が曖昧なときは、次に必要な情報だけを短く聞く
- 名前以外の話題へ脱線しない
- 最終確定できたら action=commit にする
- 曖昧・雑音・誤認識の可能性がある返答では commit しない

返却JSON形式:
{
  "action": "ask_name" | "ask_reading" | "ask_confirm" | "commit" | "fallback_manual",
  "display_text": "字幕に出す文",
  "spoken_text": "TTSに読ませる文",
  "candidate_name": "候補の漢字フルネーム。なければ空文字",
  "candidate_reading": "候補の読み仮名。ひらがな推奨。なければ空文字"
}

判断ルール:
- stage=init:
  まず名前を聞く
- stage=await_name:
  transcript から漢字フルネーム候補が取れたら ask_reading
  取れないなら ask_name
- stage=await_reading:
  transcript から読み仮名候補が取れたら ask_confirm
  取れないなら ask_reading
- stage=await_confirm:
  transcript が明確な肯定（例: はい, そうです, 合っています, 正解です）なら commit
  transcript が明確な否定なら ask_name
  transcript が曖昧、短すぎる、意味不明、誤認識っぽい場合は commit しない
  transcript に修正版の名前や漢字ヒントがあれば ask_reading または ask_confirm で候補更新
- 「名字は合っています。名前が違います」のような発話では、名字は維持して名前だけを聞き直す
- 「文章の章」「真実の真」のような説明は確認のヒントであり、肯定ではない
- 「おしまいです」「3台の間に」など名前確認と無関係な文や誤変換っぽい文で commit してはいけない
- 候補名は姓と名を含むフルネームを優先
- candidate_reading は ひらがな で返す
- display_text / spoken_text はそれぞれ60文字以内を目安に簡潔に
"""

NAME_GUIDANCE_FINALIZE_TIMEOUT_S = float(os.getenv("RECOGNITION_NAME_GUIDANCE_FINALIZE_TIMEOUT_S", "15"))


class ApproachPayload(BaseModel):
    person_id: str | None = None


@app.get("/api/tts-debug-files")
async def api_tts_debug_files():
    rows = []
    for name in os.listdir(TTS_DEBUG_WEB_DIR):
        if not name.lower().endswith(".wav"):
            continue
        full = os.path.join(TTS_DEBUG_WEB_DIR, name)
        if not os.path.isfile(full):
            continue
        st = os.stat(full)
        rows.append(
            {
                "name": name,
                "size_bytes": int(st.st_size),
                "modified_ts": float(st.st_mtime),
                "url": f"/download/tts_debug/{name}",
            }
        )
    rows.sort(key=lambda x: x["modified_ts"], reverse=True)
    return JSONResponse({"files": rows, "dir": TTS_DEBUG_WEB_DIR})


@app.get("/tts-debug", response_class=HTMLResponse)
async def tts_debug_page():
    if not os.path.exists(TTS_DEBUG_VIEWER_HTML):
        return HTMLResponse(
            "<h3>tts_debug_browser.html が見つかりません。</h3>",
            status_code=500,
        )
    with open(TTS_DEBUG_VIEWER_HTML, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


def _set_next_audio_is_registration(enabled: bool) -> None:
    if hasattr(base, "set_next_audio_is_registration"):
        base.set_next_audio_is_registration(enabled)
        return
    setattr(base, "NEXT_AUDIO_IS_REGISTRATION", enabled)


def _get_next_audio_is_registration() -> bool:
    if hasattr(base, "get_next_audio_is_registration"):
        return bool(base.get_next_audio_is_registration())
    return bool(getattr(base, "NEXT_AUDIO_IS_REGISTRATION", False))


def _clear_name_guidance_state() -> None:
    NAME_GUIDANCE.active = False
    NAME_GUIDANCE.stage = "idle"
    NAME_GUIDANCE.candidate_name = None
    NAME_GUIDANCE.candidate_reading = None
    NAME_GUIDANCE.turn_count = 0
    NAME_GUIDANCE.history.clear()
    NAME_GUIDANCE.finalizing = False
    NAME_GUIDANCE.finalizing_started_at = 0.0
    NAME_GUIDANCE.pending_commit_name = None
    NAME_GUIDANCE.pending_commit_reading = None


def _create_voice_session_state():
    if hasattr(base, "create_session_state"):
        return base.create_session_state()
    return []


def _reset_speaker_guard_state() -> int:
    speaker_guard = getattr(base, "speaker_guard", None)
    if speaker_guard is None:
        return 0
    known_speakers = getattr(speaker_guard, "known_speakers", None)
    if hasattr(speaker_guard, "bootstrap_audio_tensor"):
        speaker_guard.bootstrap_audio_tensor = None
    if isinstance(known_speakers, list):
        cleared = len(known_speakers)
        known_speakers.clear()
        return cleared
    return 0


async def _reset_conversation_context(reason: str, person_id: str | None) -> None:
    global SESSION_RESET_EPOCH
    cleared_speakers = _reset_speaker_guard_state()
    _set_next_audio_is_registration(False)
    if hasattr(base, "set_current_customer_profile"):
        base.set_current_customer_profile(None, None)
    async with STATE_LOCK:
        SESSION_RESET_EPOCH += 1
        reset_epoch = SESSION_RESET_EPOCH
        _clear_name_guidance_state()
    base.logger.info(
        "[SESSION_RESET] reason=%s person_id=%s cleared_speakers=%d epoch=%d",
        reason,
        person_id,
        cleared_speakers,
        reset_epoch,
    )


def _get_tts_model_count() -> int:
    tts_module = getattr(base, "tts_module", None)
    models = getattr(tts_module, "GLOBAL_TTS_MODELS", None)
    if not models:
        return 0
    return len(models)


def _resolve_greeting_worker_id() -> int | None:
    model_count = _get_tts_model_count()
    if model_count <= 0:
        return None
    if GREETING_TTS_WORKER_ID > 0:
        return min(GREETING_TTS_WORKER_ID, model_count)
    if model_count >= 2:
        return 2
    return 1


def _get_tts_snapshot(worker_id: int | None) -> dict | None:
    tts_module = getattr(base, "tts_module", None)
    if tts_module is None or not hasattr(tts_module, "get_tts_debug_snapshot"):
        return None
    try:
        return tts_module.get_tts_debug_snapshot(worker_id)
    except Exception:
        return {"snapshot_error": True, "worker_id": worker_id}


@app.post("/enable-registration")
async def enable_registration():
    _set_next_audio_is_registration(True)
    base.logger.info("【モード切替】次の発話を新規話者として登録します")
    await _broadcast_json({"status": "system_info", "message": "次の発話を新規話者として登録します。"})
    return JSONResponse({"message": "登録モード待機中"})


async def _broadcast_json(payload: dict) -> None:
    async with WS_CLIENTS_LOCK:
        clients = list(WS_CLIENTS)
    stale_clients: list[WebSocket] = []
    for websocket in clients:
        try:
            await websocket.send_json(payload)
        except Exception:
            stale_clients.append(websocket)
    if stale_clients:
        async with WS_CLIENTS_LOCK:
            for websocket in stale_clients:
                WS_CLIENTS.discard(websocket)


async def _broadcast_registration_candidate(person_id: str, message: str) -> None:
    await _broadcast_json(
        {
            "status": "registration_candidate",
            "person_id": person_id,
            "person_reading": NAME_GUIDANCE.candidate_reading or "",
            "message": message,
        }
    )


async def _broadcast_registration_commit(person_id: str, person_reading: str | None = None) -> None:
    await _broadcast_json(
        {
            "status": "registration_commit",
            "person_id": person_id,
            "person_reading": person_reading or "",
            "message": f"{person_id}さんとして登録します。",
        }
    )


def _build_guided_tts_text(display_text: str, spoken_text: str, candidate_name: str | None, candidate_reading: str | None) -> str:
    tts_text = (spoken_text or "").strip() or (display_text or "").strip()
    name = (candidate_name or "").strip()
    reading = (candidate_reading or "").strip()
    if not reading:
        return tts_text
    if name:
        tts_text = tts_text.replace(f"{name}（{reading}）", reading)
        tts_text = tts_text.replace(f"{name}({reading})", reading)
        tts_text = tts_text.replace(name, reading)
    # display_text 側だけに漢字＋読みを載せたいケースに備えて、読み仮名の括弧だけは落とす
    tts_text = re.sub(rf"[（(]\s*{re.escape(reading)}\s*[)）]", "", tts_text)
    tts_text = re.sub(r"\s{2,}", " ", tts_text).strip()
    return tts_text


def _extract_first_json_object(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None
    fenced = raw.replace("```json", "").replace("```", "").strip()
    try:
        parsed = json.loads(fenced)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    match = re.search(r"\{.*\}", fenced, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _append_name_guidance_history(role: str, text: str) -> None:
    clean = str(text or "").strip()
    if not clean:
        return
    NAME_GUIDANCE.history.append({"role": role, "parts": [clean]})
    if len(NAME_GUIDANCE.history) > 8:
        NAME_GUIDANCE.history = NAME_GUIDANCE.history[-8:]


async def _run_name_capture_prompt(stage: str, transcript: str, candidate_name: str | None) -> dict:
    if not getattr(answer_module, "GOOGLE_API_KEY", None):
        raise RuntimeError("GOOGLE_API_KEY が設定されていません。")
    model_instance = answer_module.genai.GenerativeModel(
        model_name=NAME_CAPTURE_MODEL,
        system_instruction=NAME_CAPTURE_SYSTEM_PROMPT,
        generation_config={"temperature": 0.2},
    )
    chat_session = model_instance.start_chat(history=NAME_GUIDANCE.history)
    prompt = json.dumps(
        {
            "stage": stage,
            "candidate_name": candidate_name or "",
            "candidate_reading": NAME_GUIDANCE.candidate_reading or "",
            "turn_count": NAME_GUIDANCE.turn_count,
            "transcript": transcript,
        },
        ensure_ascii=False,
    )
    response = await asyncio.to_thread(chat_session.send_message, prompt)
    raw_text = getattr(response, "text", "") or ""
    parsed = _extract_first_json_object(raw_text)
    if not parsed:
        raise ValueError(f"名前特定JSONの解析に失敗しました: {raw_text!r}")
    return parsed


async def _transcribe_audio_text(audio_float32_np) -> str:
    asr_model = getattr(base, "GLOBAL_ASR_MODEL_INSTANCE", None)
    if asr_model is None:
        return ""
    segments = await asyncio.to_thread(asr_model.transcribe, audio_float32_np)
    return "".join([s[2] for s in asr_model.ts_words(segments)]).strip()


async def _handle_guided_name_capture(audio_float32_np, websocket: WebSocket) -> bool:
    if not ENABLE_GUIDED_NAME_CAPTURE or not NAME_GUIDANCE.active:
        return False

    if NAME_GUIDANCE.finalizing:
        elapsed = time.monotonic() - NAME_GUIDANCE.finalizing_started_at
        if elapsed > NAME_GUIDANCE_FINALIZE_TIMEOUT_S:
            base.logger.warning(
                "[NAME_GUIDE] finalize_timeout elapsed_s=%.1f pending_name=%s",
                elapsed,
                NAME_GUIDANCE.pending_commit_name,
            )
            _clear_name_guidance_state()
            await _broadcast_json(
                {
                    "status": "system_info",
                    "message": "お名前の登録が完了しませんでした。もう一度お試しください。",
                }
            )
        else:
            await _broadcast_json(
                {
                    "status": "system_info",
                    "message": "お名前を登録しています。少々お待ちください。",
                }
            )
        return True

    text = await _transcribe_audio_text(audio_float32_np)
    if not text:
        await _broadcast_json({"status": "ignored", "message": "お名前が聞き取れませんでした。"})
        return True

    await websocket.send_json({
        "status": "transcribed",
        "question_text": text,
        "speaker_id": "guest",
    })
    NAME_GUIDANCE.turn_count += 1
    _append_name_guidance_history("user", text)
    base.logger.info("[NAME_GUIDE] stage=%s turn=%d text=%r", NAME_GUIDANCE.stage, NAME_GUIDANCE.turn_count, text)

    try:
        result = await _run_name_capture_prompt(NAME_GUIDANCE.stage, text, NAME_GUIDANCE.candidate_name)
    except Exception as exc:
        base.logger.warning("[NAME_GUIDE] prompt_failed err=%s", exc)
        await _broadcast_registration_candidate("", "お名前の確認に失敗しました。画面から入力してください。")
        await _broadcast_json(
            {
                "status": "system_info",
                "message": "お名前の確認に失敗しました。画面から入力してください。",
            }
        )
        return True

    action = str(result.get("action") or "").strip()
    display_text = str(result.get("display_text") or "").strip()
    spoken_text = str(result.get("spoken_text") or "").strip()
    candidate_name = str(result.get("candidate_name") or "").strip()
    candidate_reading = str(result.get("candidate_reading") or "").strip()
    if candidate_name:
        NAME_GUIDANCE.candidate_name = candidate_name
    if candidate_reading:
        NAME_GUIDANCE.candidate_reading = candidate_reading

    if not display_text and spoken_text:
        display_text = spoken_text
    if not spoken_text:
        spoken_text = display_text or "お名前をもう一度お願いします。"
    if not display_text:
        display_text = "お名前をもう一度お願いします。"

    tts_text = _build_guided_tts_text(
        display_text,
        spoken_text,
        NAME_GUIDANCE.candidate_name,
        NAME_GUIDANCE.candidate_reading,
    )

    _append_name_guidance_history("model", display_text)
    base.logger.info(
        "[NAME_GUIDE] result action=%s candidate=%s display=%r tts=%r reading=%s",
        action,
        NAME_GUIDANCE.candidate_name,
        display_text,
        tts_text,
        NAME_GUIDANCE.candidate_reading,
    )

    if action == "commit" and NAME_GUIDANCE.candidate_name:
        person_id = NAME_GUIDANCE.candidate_name
        person_reading = NAME_GUIDANCE.candidate_reading or ""
        NAME_GUIDANCE.active = True
        NAME_GUIDANCE.stage = "finalizing"
        NAME_GUIDANCE.finalizing = True
        NAME_GUIDANCE.finalizing_started_at = time.monotonic()
        NAME_GUIDANCE.pending_commit_name = person_id
        NAME_GUIDANCE.pending_commit_reading = person_reading
        await _broadcast_registration_commit(person_id, person_reading)
        await _broadcast_spoken_text(display_text, tts_text)
        return True

    if action == "ask_confirm":
        NAME_GUIDANCE.stage = "await_confirm"
        await _broadcast_registration_candidate(NAME_GUIDANCE.candidate_name or "", display_text)
        await _broadcast_spoken_text(display_text, tts_text)
        return True

    if action == "ask_reading":
        NAME_GUIDANCE.stage = "await_reading"
        await _broadcast_registration_candidate(NAME_GUIDANCE.candidate_name or "", display_text)
        await _broadcast_spoken_text(display_text, tts_text)
        return True

    if action in {"ask_name", "fallback_manual"}:
        NAME_GUIDANCE.stage = "await_name"
        if action == "ask_name":
            NAME_GUIDANCE.candidate_name = None
            NAME_GUIDANCE.candidate_reading = None
        if action == "fallback_manual":
            await _broadcast_registration_candidate(NAME_GUIDANCE.candidate_name or "", display_text)
            await _broadcast_json({"status": "system_info", "message": display_text})
            return True
        await _broadcast_registration_candidate(NAME_GUIDANCE.candidate_name or "", display_text)
        await _broadcast_spoken_text(display_text, tts_text)
        return True

    await _broadcast_registration_candidate(NAME_GUIDANCE.candidate_name or "", display_text)
    await _broadcast_spoken_text(display_text, tts_text)
    return True


async def _speak_text_to_websocket(websocket: WebSocket, text: str, spoken_text: str | None = None) -> None:
    display_text = (text or "").strip()
    tts_text = (spoken_text or "").strip() or display_text
    greet_start = time.perf_counter()
    worker_id = _resolve_greeting_worker_id()
    model_snapshot = _get_tts_snapshot(worker_id)
    pcm_bytes = GREETING_PCM_CACHE.get(tts_text)
    source = "cache" if pcm_bytes else "runtime"
    base.logger.info(
        "[GREETING] start display=%r tts=%r worker_id=%s source=%s model=%s",
        display_text,
        tts_text,
        worker_id,
        source,
        model_snapshot,
    )
    if pcm_bytes is None:
        synth_start = time.perf_counter()
        if worker_id is not None and hasattr(base, "synthesize_speech_to_memory_for_worker"):
            pcm_bytes = await asyncio.to_thread(base.synthesize_speech_to_memory_for_worker, tts_text, worker_id)
        else:
            pcm_bytes = await asyncio.to_thread(base.synthesize_speech_to_memory, tts_text)
        synth_ms = (time.perf_counter() - synth_start) * 1000.0
        base.logger.info(
            "[GREETING] synth_done display=%r tts=%r worker_id=%s bytes=%s synth_ms=%.1f",
            display_text,
            tts_text,
            worker_id,
            len(pcm_bytes) if pcm_bytes else 0,
            synth_ms,
        )
    if not pcm_bytes:
        return
    send_start = time.perf_counter()
    await websocket.send_json({"status": "reply_chunk", "text_chunk": display_text})
    await websocket.send_json(
        {
            "status": "audio_chunk_meta",
            "sentence_id": 1,
            "chunk_id": 1,
            "global_chunk_id": 1,
            "arrival_seq": 1,
            "byte_len": len(pcm_bytes),
            "sample_rate": 16000,
        }
    )
    await websocket.send_bytes(pcm_bytes)
    await websocket.send_json({"status": "audio_sentence_done", "sentence_id": 1, "last_chunk_id": 1, "total_bytes": len(pcm_bytes)})
    await websocket.send_json({"status": "complete", "answer_text": display_text})
    send_ms = (time.perf_counter() - send_start) * 1000.0
    total_ms = (time.perf_counter() - greet_start) * 1000.0
    base.logger.info(
        "[GREETING] send_done display=%r tts=%r worker_id=%s bytes=%d send_ms=%.1f total_ms=%.1f",
        display_text,
        tts_text,
        worker_id,
        len(pcm_bytes),
        send_ms,
        total_ms,
    )


def _build_greeting_text(person_id: str | None, known_face: bool, person_reading: str | None = None) -> str:
    if known_face and person_id:
        spoken_name = person_reading or person_id
        return KNOWN_GREETING_TEMPLATE.format(person_id=spoken_name)
    return UNKNOWN_GREETING_TEXT


async def _broadcast_greeting(person_id: str | None, known_face: bool, person_reading: str | None = None) -> None:
    text = _build_greeting_text(person_id, known_face, person_reading)
    async with WS_CLIENTS_LOCK:
        clients = list(WS_CLIENTS)
    base.logger.info(
        "[GREETING] broadcast text=%r clients=%d person_id=%s known_face=%s",
        text,
        len(clients),
        person_id,
        known_face,
    )
    for websocket in clients:
        try:
            await _speak_text_to_websocket(websocket, text)
        except Exception:
            pass


async def _broadcast_spoken_text(text: str, spoken_text: str | None = None) -> None:
    async with WS_CLIENTS_LOCK:
        clients = list(WS_CLIENTS)
    base.logger.info("[GUIDE] broadcast display=%r tts=%r clients=%d", text, spoken_text or text, len(clients))
    for websocket in clients:
        try:
            await _speak_text_to_websocket(websocket, text, spoken_text)
        except Exception:
            pass


async def _handle_approach(person_id: str | None) -> dict[str, object]:
    await _reset_conversation_context("approach", person_id)
    async with STATE_LOCK:
        STATE.active = True
        STATE.person_id = None
        STATE.person_reading = None
        STATE.greeted = False
        STATE.recognition_pending = True
    await _broadcast_json(
        {
            "status": "system_info",
            "message": "接近を検知しました。顔認証中です。",
        }
    )
    base.logger.info(
        "[APPROACH] pending_face_recognition person_id=%s",
        person_id,
    )
    return {"ok": True, "active": True, "person_id": None, "recognition_pending": True}


async def _handle_face_recognition(person_id: str | None, known_face: bool, person_reading: str | None = None) -> dict[str, object]:
    async with STATE_LOCK:
        bootstrapped = False
        promoted_after_unknown = False
        if not STATE.active:
            STATE.active = True
            STATE.person_id = None
            STATE.greeted = False
            STATE.recognition_pending = True
            bootstrapped = True
        if STATE.greeted:
            if known_face and person_id and not STATE.person_id:
                STATE.person_id = person_id
                STATE.person_reading = person_reading
                STATE.recognition_pending = False
                promoted_after_unknown = True
            else:
                return {"ok": True, "active": True, "person_id": STATE.person_id, "already_greeted": True}
        STATE.person_id = person_id if known_face else None
        STATE.person_reading = person_reading if known_face else None
        STATE.greeted = True
        STATE.recognition_pending = False
    if bootstrapped:
        base.logger.info("[FACE_RESULT] bootstrapped_without_approach known_face=%s person_id=%s", known_face, person_id)
    if promoted_after_unknown:
        if NAME_GUIDANCE.finalizing:
            base.logger.info(
                "[NAME_GUIDE] finalize_done person_id=%s reading=%s",
                person_id,
                person_reading,
            )
        _clear_name_guidance_state()
        if hasattr(base, "set_current_customer_profile"):
            base.set_current_customer_profile(person_id, person_reading)
        await _broadcast_json(
            {
                "status": "system_info",
                "message": f"{person_id}さんとして登録しました。",
            }
        )
        base.logger.info("[FACE_RESULT] promoted_after_unknown person_id=%s", person_id)
        return {"ok": True, "active": True, "person_id": person_id, "known_face": True, "promoted_after_unknown": True}
    await _broadcast_json(
        {
            "status": "system_info",
            "message": (
                f"顔認証が完了しました。person_id={person_id}"
                if known_face and person_id
                else "顔認証が完了しました。"
            ),
        }
    )
    if hasattr(base, "set_current_customer_profile"):
        base.set_current_customer_profile(person_id if known_face else None, person_reading if known_face else None)
    if known_face:
        if NAME_GUIDANCE.finalizing:
            base.logger.info(
                "[NAME_GUIDE] finalize_done person_id=%s reading=%s",
                person_id,
                person_reading,
            )
        _clear_name_guidance_state()
    await _broadcast_greeting(person_id if known_face else None, known_face, person_reading if known_face else None)
    if not known_face:
        await _broadcast_json(
            {
                "status": "registration_prompt",
                "message": "はじめての方は、お名前を入力すると顔を登録できます。",
            }
        )
        if ENABLE_GUIDED_NAME_CAPTURE and not NAME_CAPTURE_UI_FIRST:
            _clear_name_guidance_state()
            NAME_GUIDANCE.active = True
            NAME_GUIDANCE.stage = "await_name"
            try:
                result = await _run_name_capture_prompt("init", "", None)
                display_prompt = str(result.get("display_text") or result.get("spoken_text") or "").strip()
                spoken_prompt = str(result.get("spoken_text") or display_prompt).strip()
                prompt = display_prompt or "はじめまして。お名前を教えてください。"
            except Exception as exc:
                base.logger.warning("[NAME_GUIDE] init_prompt_failed err=%s", exc)
                prompt = "はじめまして。お名前を教えてください。"
                spoken_prompt = prompt
            _append_name_guidance_history("model", prompt)
            await _broadcast_registration_candidate("", prompt)
            await _broadcast_spoken_text(prompt, spoken_prompt)
    base.logger.info("[FACE_RESULT] known_face=%s person_id=%s", known_face, person_id)
    return {"ok": True, "active": True, "person_id": person_id if known_face else None, "known_face": known_face}


async def _handle_leave(person_id: str | None) -> dict[str, object]:
    await _reset_conversation_context("leave", person_id)
    async with STATE_LOCK:
        STATE.active = False
        STATE.person_id = person_id
        STATE.person_reading = None
        STATE.greeted = False
        STATE.recognition_pending = False
    await _broadcast_json(
        {
            "status": "system_info",
            "message": f"認識システムが離脱を検知しました。person_id={person_id or 'unknown'}",
        }
    )
    base.logger.info("[LEAVE] handled person_id=%s", person_id)
    return {"ok": True, "active": False, "person_id": person_id}


async def _handle_control_message(websocket: WebSocket, raw_text: str) -> None:
    try:
        payload = json.loads(raw_text)
    except Exception:
        base.logger.warning("[WS_CONTROL] invalid_json text=%r", raw_text[:200])
        return

    payload_type = payload.get("type")
    if payload_type == "diag_ping":
        await websocket.send_json(
            {
                "status": "diag_pong",
                "client_sent_ms": payload.get("client_sent_ms"),
                "server_recv_ms": int(time.time() * 1000),
            }
        )
        base.logger.info("[WS_DIAG] ping client=%s client_sent_ms=%s", websocket.client, payload.get("client_sent_ms"))
        return

    if payload_type == "client_audio_capture_started":
        base.logger.info("[WS_AUDIO] capture_started client=%s client_sent_ms=%s", websocket.client, payload.get("client_sent_ms"))
        return

    if payload_type != "recognition_event":
        base.logger.info("[WS_CONTROL] ignored payload=%s", payload)
        return

    event_name = payload.get("event")
    person_id = payload.get("person_id")
    person_reading = payload.get("person_reading")
    base.logger.info("[WS_CONTROL] event=%s person_id=%s person_reading=%s client=%s", event_name, person_id, person_reading, websocket.client)

    if event_name == "approach":
        await _handle_approach(person_id)
    elif event_name == "recognized_face":
        await _handle_face_recognition(person_id, True, person_reading)
    elif event_name == "unknown_face":
        await _handle_face_recognition(None, False)
    elif event_name == "leave":
        await _handle_leave(person_id)
    else:
        base.logger.warning("[WS_CONTROL] unknown_event payload=%s", payload)


@app.on_event("startup")
async def startup_diagnostics() -> None:
    worker_id = _resolve_greeting_worker_id()
    base.logger.info(
        "[GATE] startup mode=%s base=%s barge_in=%s greeting_worker_id=%s tts_model_count=%d",
        VOICE_APP_MODE,
        BASE_MODULE_NAME,
        ENABLE_BARGE_IN,
        worker_id,
        _get_tts_model_count(),
    )
    if worker_id is None:
        return
    greeting_text = UNKNOWN_GREETING_TEXT
    try:
        start = time.perf_counter()
        pcm_bytes = await asyncio.to_thread(base.synthesize_speech_to_memory_for_worker, greeting_text, worker_id)
        if pcm_bytes:
            GREETING_PCM_CACHE[greeting_text] = pcm_bytes
        base.logger.info(
            "[GREETING] cache_ready text=%r worker_id=%s bytes=%d ms=%.1f",
            greeting_text,
            worker_id,
            len(pcm_bytes) if pcm_bytes else 0,
            (time.perf_counter() - start) * 1000.0,
        )
    except Exception as exc:
        base.logger.warning("[GREETING] cache_failed text=%r err=%s", greeting_text, exc)


@app.post("/recognition/approach")
async def recognition_approach(payload: ApproachPayload) -> dict[str, object]:
    return await _handle_approach(payload.person_id)


@app.post("/recognition/leave")
async def recognition_leave(payload: ApproachPayload) -> dict[str, object]:
    return await _handle_leave(payload.person_id)


@app.get("/recognition/state")
async def recognition_state() -> dict[str, object]:
    async with STATE_LOCK:
        return {"active": STATE.active, "person_id": STATE.person_id}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    base.logger.info(
        "[WS] Incoming handshake client=%s origin=%s host=%s",
        websocket.client,
        websocket.headers.get("origin"),
        websocket.headers.get("host"),
    )
    await websocket.accept()
    base.logger.info("[WS] Client Connected (recognition gate).")
    async with WS_CLIENTS_LOCK:
        WS_CLIENTS.add(websocket)

    vad_iterator = base.VADIterator(
        base.vad_model,
        threshold=0.95,
        sampling_rate=16000,
        min_silence_duration_ms=200,
        speech_pad_ms=50,
    )

    audio_buffer = []
    is_speaking = False
    interruption_triggered = False
    binary_chunk_count = 0
    first_binary_logged = False
    connect_started = time.perf_counter()

    window_size_samples = 512
    sample_rate = 16000
    check_speaker_samples = 30000
    session_state = _create_voice_session_state()
    session_reset_epoch = SESSION_RESET_EPOCH

    try:
        await websocket.send_json({"status": "system_info", "message": "認識システムからの接近待ちです。"})
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect()
            data_text = message.get("text")
            if data_text is not None:
                await _handle_control_message(websocket, data_text)
                if session_reset_epoch != SESSION_RESET_EPOCH:
                    session_state = _create_voice_session_state()
                    session_reset_epoch = SESSION_RESET_EPOCH
                continue
            data_bytes = message.get("bytes")
            if data_bytes is None:
                continue
            if session_reset_epoch != SESSION_RESET_EPOCH:
                session_state = _create_voice_session_state()
                session_reset_epoch = SESSION_RESET_EPOCH
            binary_chunk_count += 1
            if not first_binary_logged:
                first_binary_logged = True
                base.logger.info(
                    "[WS_AUDIO] first_chunk client=%s after_connect_ms=%.1f bytes=%d",
                    websocket.client,
                    (time.perf_counter() - connect_started) * 1000.0,
                    len(data_bytes),
                )
            elif binary_chunk_count % 32 == 0:
                base.logger.info(
                    "[WS_AUDIO] chunk_count=%d client=%s",
                    binary_chunk_count,
                    websocket.client,
                )
            async with STATE_LOCK:
                current_active = STATE.active
            if not current_active:
                continue

            audio_chunk_np = np.frombuffer(data_bytes, dtype=np.float32).copy()
            offset = 0
            while offset + window_size_samples <= len(audio_chunk_np):
                window_np = audio_chunk_np[offset : offset + window_size_samples]
                offset += window_size_samples
                window_tensor = torch.from_numpy(window_np).unsqueeze(0).to(base.DEVICE)

                speech_dict = await asyncio.to_thread(vad_iterator, window_tensor, return_seconds=True)

                if speech_dict:
                    if "start" in speech_dict:
                        base.logger.info("🗣️ Speech START")
                        is_speaking = True
                        interruption_triggered = False
                        audio_buffer = [window_np]
                        await websocket.send_json({"status": "processing", "message": "👂 聞いています..."})
                    elif "end" in speech_dict:
                        base.logger.info("🤫 Speech END")
                        if is_speaking:
                            is_speaking = False
                            audio_buffer.append(window_np)
                            full_audio = np.concatenate(audio_buffer)

                            if len(full_audio) / sample_rate < 0.2:
                                base.logger.info("Noise detected")
                                await websocket.send_json({"status": "ignored", "message": "会話が短すぎます。"})
                            else:
                                await websocket.send_json({"status": "processing", "message": "🧠 AI思考中..."})
                                pipeline_start = time.perf_counter()
                                handled_by_name_guide = await _handle_guided_name_capture(full_audio, websocket)
                                if not handled_by_name_guide:
                                    await base.process_voice_pipeline(full_audio, websocket, session_state)
                                base.logger.info(
                                    "[GATE_PIPELINE] process_voice_pipeline_done samples=%d duration_s=%.2f total_ms=%.1f",
                                    len(full_audio),
                                    len(full_audio) / sample_rate,
                                    (time.perf_counter() - pipeline_start) * 1000.0,
                                )
                            audio_buffer = []
                else:
                    if is_speaking:
                        audio_buffer.append(window_np)
                        current_len = sum(len(c) for c in audio_buffer)
                        if (
                            ENABLE_BARGE_IN
                            and not interruption_triggered
                            and not _get_next_audio_is_registration()
                            and current_len > check_speaker_samples
                        ):
                            temp_audio = np.concatenate(audio_buffer)
                            temp_tensor = torch.from_numpy(temp_audio).float().unsqueeze(0)
                            barge_start = time.perf_counter()
                            is_verified, spk_id = await asyncio.to_thread(base.speaker_guard.identify_speaker, temp_tensor)
                            barge_ms = (time.perf_counter() - barge_start) * 1000.0
                            base.logger.info(
                                "[BARGE_IN] checked duration_s=%.2f identify_ms=%.1f verified=%s speaker=%s",
                                current_len / sample_rate,
                                barge_ms,
                                is_verified,
                                spk_id,
                            )
                            if is_verified:
                                base.logger.info(f"⚡ [Barge-in] {spk_id} の声を検知！停止指示。")
                                await websocket.send_json({"status": "interrupt", "message": "🛑 音声停止"})
                                interruption_triggered = True

    except WebSocketDisconnect:
        base.logger.info("[WS] Disconnected")
    except Exception as exc:
        base.logger.error(f"[WS ERROR] {exc}", exc_info=True)
    finally:
        vad_iterator.reset_states()
        async with WS_CLIENTS_LOCK:
            WS_CLIENTS.discard(websocket)


@app.get("/", response_class=HTMLResponse)
async def root():
    html = await base.get_root()
    html = html.replace("Team Chat AI", "Recognition Gate Chat AI", 1)
    html = html.replace("接続待機中...", "認識システムからの接近待ち...", 1)
    return HTMLResponse(html)


if __name__ == "__main__":
    port = int(base.os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
