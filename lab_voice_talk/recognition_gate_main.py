import asyncio
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

import parallel_faster_main as base


app = FastAPI()


@dataclass
class ActivationState:
    active: bool = False
    person_id: str | None = None


STATE = ActivationState()
STATE_LOCK = asyncio.Lock()
WS_CLIENTS: set[WebSocket] = set()
WS_CLIENTS_LOCK = asyncio.Lock()
GREETING_PCM_CACHE: dict[str, bytes] = {}
ENABLE_BARGE_IN = os.getenv("RECOGNITION_ENABLE_BARGE_IN", "1") == "1"
GREETING_TTS_WORKER_ID = int(os.getenv("RECOGNITION_GREETING_TTS_WORKER_ID", "0"))


class ApproachPayload(BaseModel):
    person_id: str | None = None


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
    base.NEXT_AUDIO_IS_REGISTRATION = True
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


async def _broadcast_greeting(person_id: str | None) -> None:
    text = f"{person_id}さん、こんにちは。" if person_id else "こんにちは。"
    async with WS_CLIENTS_LOCK:
        clients = list(WS_CLIENTS)
    base.logger.info(
        "[GREETING] broadcast text=%r clients=%d person_id=%s",
        text,
        len(clients),
        person_id,
    )
    for websocket in clients:
        try:
            await _speak_text_to_websocket(websocket, text)
        except Exception:
            pass


async def _handle_approach(person_id: str | None) -> dict[str, object]:
    start = time.perf_counter()
    async with STATE_LOCK:
        was_active = STATE.active
        STATE.active = True
        STATE.person_id = person_id
    await _broadcast_json(
        {
            "status": "system_info",
            "message": f"認識システムが接近を検知しました。person_id={person_id or 'unknown'}",
        }
    )
    if not was_active:
        await _broadcast_greeting(person_id)
    base.logger.info(
        "[APPROACH] handled person_id=%s was_active=%s total_ms=%.1f",
        person_id,
        was_active,
        (time.perf_counter() - start) * 1000.0,
    )
    return {"ok": True, "active": True, "person_id": person_id}


async def _handle_leave(person_id: str | None) -> dict[str, object]:
    async with STATE_LOCK:
        STATE.active = False
        STATE.person_id = person_id
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

    if payload.get("type") != "recognition_event":
        base.logger.info("[WS_CONTROL] ignored payload=%s", payload)
        return

    event_name = payload.get("event")
    person_id = payload.get("person_id")
    base.logger.info("[WS_CONTROL] event=%s person_id=%s client=%s", event_name, person_id, websocket.client)

    if event_name == "approach":
        await _handle_approach(person_id)
    elif event_name == "leave":
        await _handle_leave(person_id)
    else:
        base.logger.warning("[WS_CONTROL] unknown_event payload=%s", payload)


@app.on_event("startup")
async def startup_diagnostics() -> None:
    worker_id = _resolve_greeting_worker_id()
    base.logger.info(
        "[GATE] startup barge_in=%s greeting_worker_id=%s tts_model_count=%d",
        ENABLE_BARGE_IN,
        worker_id,
        _get_tts_model_count(),
    )
    if worker_id is None:
        return
    greeting_text = "こんにちは。"
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

    window_size_samples = 512
    sample_rate = 16000
    check_speaker_samples = 30000
    chat_history = []

    try:
        await websocket.send_json({"status": "system_info", "message": "認識システムからの接近待ちです。"})
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect()
            data_text = message.get("text")
            if data_text is not None:
                await _handle_control_message(websocket, data_text)
                continue
            data_bytes = message.get("bytes")
            if data_bytes is None:
                continue
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
                                await base.process_voice_pipeline(full_audio, websocket, chat_history)
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
                            and not base.NEXT_AUDIO_IS_REGISTRATION
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
