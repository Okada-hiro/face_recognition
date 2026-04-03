from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import cv2
import numpy as np
import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


REPO_ROOT = Path(__file__).resolve().parents[1]
SCREEN_ROOT = REPO_ROOT / "application" / "screen"
PORT = int(os.environ.get("PORT", "8005"))
ASSET_VERSION = str(int(time.time()))
logger = logging.getLogger("reception_ui_preview")

app = FastAPI(title="Reception UI Preview", version="1.0.0")
app.mount("/app-assets", StaticFiles(directory=str(SCREEN_ROOT)), name="app-assets")

FRAME_INDEX = 0
APPROACH_SENT = False
PREVIEW_MODE = "unknown"
PREVIEW_PERSON_ID = "田中"
PREVIEW_CENTER_X = 0.68
PREVIEW_CENTER_Y = 0.42


class FaceRegistrationPayload(BaseModel):
    person_id: str


def _html_response(html_text: str) -> HTMLResponse:
    return HTMLResponse(
        html_text,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def _load_screen_html(filename: str) -> str:
    target = SCREEN_ROOT / filename
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"screen file not found: {filename}")
    html_text = target.read_text(encoding="utf-8")
    html_text = html_text.replace("./styles.css", f"/app-assets/styles.css?v={ASSET_VERSION}")
    html_text = html_text.replace("./app.js", f"/app-assets/app.js?v={ASSET_VERSION}")
    html_text = html_text.replace("./live.js", f"/app-assets/live.js?v={ASSET_VERSION}")
    return html_text


def _inject_runtime_config(html_text: str, request: Request) -> str:
    config = {
        "visionHttpBase": str(request.base_url).rstrip("/"),
        "voiceWsUrl": "/ws",
    }
    config_json = json.dumps(config, ensure_ascii=False)
    script = f'<script>window.RECEPTION_CONFIG = {config_json};</script>'
    live_js_tag = '<script src="/app-assets/live.js"></script>'
    if live_js_tag in html_text:
        return html_text.replace(live_js_tag, f"{script}\n  {live_js_tag}")
    return html_text.replace("</body>", f"  {script}\n</body>")


def _current_preview_state() -> dict[str, object]:
    if PREVIEW_MODE == "idle":
        return {
            "person_count": 0,
            "face_count": 0,
            "match_count": 0,
            "person_id": "",
        }
    if PREVIEW_MODE == "recognized":
        return {
            "person_count": 1,
            "face_count": 1,
            "match_count": 1,
            "person_id": PREVIEW_PERSON_ID,
        }
    return {
        "person_count": 1,
        "face_count": 1,
        "match_count": 0,
        "person_id": "",
    }


@app.get("/", response_class=HTMLResponse)
async def root(request: Request) -> HTMLResponse:
    html_text = _load_screen_html("live.html")
    return _html_response(_inject_runtime_config(html_text, request))


@app.get("/app", response_class=HTMLResponse)
async def app_page(request: Request) -> HTMLResponse:
    return await root(request)


@app.get("/reception", response_class=HTMLResponse)
async def reception_page(request: Request) -> HTMLResponse:
    return await root(request)


@app.get("/manual", response_class=HTMLResponse)
async def manual_page() -> HTMLResponse:
    return _html_response(_load_screen_html("index.html"))


@app.post("/api/live-frame")
async def live_frame(frame: UploadFile = File(...)) -> Response:
    global FRAME_INDEX, APPROACH_SENT

    data = await frame.read()
    np_buffer = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(np_buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Could not decode uploaded frame.")

    FRAME_INDEX += 1
    state = _current_preview_state()
    track_events = []
    if state["person_count"] > 0 and not APPROACH_SENT:
        track_events = [{"track_id": 1, "event_type": "approached", "person_id": state["person_id"] or None}]
        APPROACH_SENT = True

    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to encode frame.")

    headers = {
        "x-frame-index": str(FRAME_INDEX),
        "x-match-count": str(state["match_count"]),
        "x-face-count": str(state["face_count"]),
        "x-person-count": str(state["person_count"]),
        "x-primary-person-id": state["person_id"],
        "x-primary-person-cx": f"{PREVIEW_CENTER_X:.4f}",
        "x-primary-person-cy": f"{PREVIEW_CENTER_Y:.4f}",
        "x-track-events": json.dumps(track_events, ensure_ascii=True),
    }
    return Response(content=encoded.tobytes(), media_type="image/jpeg", headers=headers)


@app.post("/api/register-face")
async def register_face(payload: FaceRegistrationPayload) -> JSONResponse:
    global PREVIEW_MODE, PREVIEW_PERSON_ID
    PREVIEW_PERSON_ID = payload.person_id.strip() or PREVIEW_PERSON_ID
    PREVIEW_MODE = "recognized"
    logger.info("[UI_PREVIEW] registered person_id=%s", PREVIEW_PERSON_ID)
    return JSONResponse({"ok": True, "person_id": PREVIEW_PERSON_ID})


@app.post("/api/preview-mode/{mode}")
async def preview_mode(mode: str) -> JSONResponse:
    global PREVIEW_MODE, APPROACH_SENT
    if mode not in {"idle", "unknown", "recognized"}:
        raise HTTPException(status_code=400, detail="mode must be idle, unknown, or recognized")
    PREVIEW_MODE = mode
    APPROACH_SENT = False
    return JSONResponse({"ok": True, "mode": PREVIEW_MODE})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({"status": "system_info", "message": "UI確認用の軽量プレビューです。"})

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect()
            if message.get("bytes") is not None:
                continue
            raw_text = message.get("text")
            if raw_text is None:
                continue
            payload = json.loads(raw_text)
            payload_type = payload.get("type")
            if payload_type == "diag_ping":
                await websocket.send_json(
                    {
                        "status": "diag_pong",
                        "client_sent_ms": payload.get("client_sent_ms"),
                        "server_recv_ms": int(time.time() * 1000),
                    }
                )
                continue
            if payload_type != "recognition_event":
                continue

            event_name = payload.get("event")
            person_id = payload.get("person_id")
            if event_name == "approach":
                await websocket.send_json({"status": "system_info", "message": "接近を検知しました。顔認証中です。"})
            elif event_name == "unknown_face":
                await websocket.send_json({"status": "system_info", "message": "顔認証が完了しました。"})
                await websocket.send_json({"status": "reply_chunk", "text_chunk": "こんにちは。"})
                await websocket.send_json({"status": "complete", "answer_text": "こんにちは。"})
                await websocket.send_json({"status": "registration_prompt", "message": "お名前を入力すると、その場で表示確認できます。"})
            elif event_name == "recognized_face":
                name = person_id or PREVIEW_PERSON_ID
                await websocket.send_json({"status": "system_info", "message": f"{name}さんとして認識しました。"})
                await websocket.send_json({"status": "reply_chunk", "text_chunk": f"{name}さん、こんにちは。"})
                await websocket.send_json({"status": "complete", "answer_text": f"{name}さん、こんにちは。"})
            elif event_name == "leave":
                await websocket.send_json({"status": "system_info", "message": "離脱を検知しました。"})
    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger.info("[UI_PREVIEW] starting on port %s", PORT)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
