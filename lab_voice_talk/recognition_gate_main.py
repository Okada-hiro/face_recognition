import asyncio
import importlib
import json
import os
import time
from dataclasses import dataclass

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

VOICE_APP_MODE = os.getenv("RECOGNITION_VOICE_APP_MODE", "prod").strip().lower()
BASE_MODULE_NAME = "sample_withface_main" if VOICE_APP_MODE == "sample" else "parallel_faster_main"
base = importlib.import_module(BASE_MODULE_NAME)


app = FastAPI()


@dataclass
class ActivationState:
    active: bool = False
    person_id: str | None = None
    greeted: bool = False
    recognition_pending: bool = False


STATE = ActivationState()
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


class ApproachPayload(BaseModel):
    person_id: str | None = None


def _set_next_audio_is_registration(enabled: bool) -> None:
    if hasattr(base, "set_next_audio_is_registration"):
        base.set_next_audio_is_registration(enabled)
        return
    setattr(base, "NEXT_AUDIO_IS_REGISTRATION", enabled)


def _get_next_audio_is_registration() -> bool:
    if hasattr(base, "get_next_audio_is_registration"):
        return bool(base.get_next_audio_is_registration())
    return bool(getattr(base, "NEXT_AUDIO_IS_REGISTRATION", False))


def _create_voice_session_state():
    if hasattr(base, "create_session_state"):
        return base.create_session_state()
    return []


def _reset_speaker_guard_state() -> int:
    speaker_guard = getattr(base, "speaker_guard", None)
    if speaker_guard is None:
        return 0
    known_speakers = getattr(speaker_guard, "known_speakers", None)
    if isinstance(known_speakers, list):
        cleared = len(known_speakers)
        known_speakers.clear()
        return cleared
    return 0


async def _reset_conversation_context(reason: str, person_id: str | None) -> None:
    global SESSION_RESET_EPOCH
    cleared_speakers = _reset_speaker_guard_state()
    _set_next_audio_is_registration(False)
    async with STATE_LOCK:
        SESSION_RESET_EPOCH += 1
        reset_epoch = SESSION_RESET_EPOCH
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


async def _speak_text_to_websocket(websocket: WebSocket, text: str) -> None:
    greet_start = time.perf_counter()
    worker_id = _resolve_greeting_worker_id()
    model_snapshot = _get_tts_snapshot(worker_id)
    pcm_bytes = GREETING_PCM_CACHE.get(text)
    source = "cache" if pcm_bytes else "runtime"
    base.logger.info(
        "[GREETING] start text=%r worker_id=%s source=%s model=%s",
        text,
        worker_id,
        source,
        model_snapshot,
    )
    if pcm_bytes is None:
        synth_start = time.perf_counter()
        if worker_id is not None and hasattr(base, "synthesize_speech_to_memory_for_worker"):
            pcm_bytes = await asyncio.to_thread(base.synthesize_speech_to_memory_for_worker, text, worker_id)
        else:
            pcm_bytes = await asyncio.to_thread(base.synthesize_speech_to_memory, text)
        synth_ms = (time.perf_counter() - synth_start) * 1000.0
        base.logger.info(
            "[GREETING] synth_done text=%r worker_id=%s bytes=%s synth_ms=%.1f",
            text,
            worker_id,
            len(pcm_bytes) if pcm_bytes else 0,
            synth_ms,
        )
    if not pcm_bytes:
        return
    send_start = time.perf_counter()
    await websocket.send_json({"status": "reply_chunk", "text_chunk": text})
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
    await websocket.send_json({"status": "complete", "answer_text": text})
    send_ms = (time.perf_counter() - send_start) * 1000.0
    total_ms = (time.perf_counter() - greet_start) * 1000.0
    base.logger.info(
        "[GREETING] send_done text=%r worker_id=%s bytes=%d send_ms=%.1f total_ms=%.1f",
        text,
        worker_id,
        len(pcm_bytes),
        send_ms,
        total_ms,
    )


def _build_greeting_text(person_id: str | None, known_face: bool) -> str:
    if known_face and person_id:
        return KNOWN_GREETING_TEMPLATE.format(person_id=person_id)
    return UNKNOWN_GREETING_TEXT


async def _broadcast_greeting(person_id: str | None, known_face: bool) -> None:
    text = _build_greeting_text(person_id, known_face)
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


async def _handle_approach(person_id: str | None) -> dict[str, object]:
    await _reset_conversation_context("approach", person_id)
    async with STATE_LOCK:
        STATE.active = True
        STATE.person_id = None
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


async def _handle_face_recognition(person_id: str | None, known_face: bool) -> dict[str, object]:
    async with STATE_LOCK:
        bootstrapped = False
        if not STATE.active:
            STATE.active = True
            STATE.person_id = None
            STATE.greeted = False
            STATE.recognition_pending = True
            bootstrapped = True
        if STATE.greeted:
            return {"ok": True, "active": True, "person_id": STATE.person_id, "already_greeted": True}
        STATE.person_id = person_id if known_face else None
        STATE.greeted = True
        STATE.recognition_pending = False
    if bootstrapped:
        base.logger.info("[FACE_RESULT] bootstrapped_without_approach known_face=%s person_id=%s", known_face, person_id)
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
    await _broadcast_greeting(person_id if known_face else None, known_face)
    base.logger.info("[FACE_RESULT] known_face=%s person_id=%s", known_face, person_id)
    return {"ok": True, "active": True, "person_id": person_id if known_face else None, "known_face": known_face}


async def _handle_leave(person_id: str | None) -> dict[str, object]:
    await _reset_conversation_context("leave", person_id)
    async with STATE_LOCK:
        STATE.active = False
        STATE.person_id = person_id
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
    base.logger.info("[WS_CONTROL] event=%s person_id=%s client=%s", event_name, person_id, websocket.client)

    if event_name == "approach":
        await _handle_approach(person_id)
    elif event_name == "recognized_face":
        await _handle_face_recognition(person_id, True)
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
