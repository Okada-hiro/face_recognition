from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles


REPO_ROOT = Path(__file__).resolve().parents[1]
SCREEN_ROOT = REPO_ROOT / "application" / "screen"
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", os.getenv("PORT", "8005")))
VISION_PORT = int(os.getenv("RECEPTION_VISION_PORT", "8000"))
VOICE_PORT = int(os.getenv("RECEPTION_VOICE_PORT", "8002"))
VISION_PUBLIC_BASE = os.getenv("RECEPTION_VISION_PUBLIC_BASE", "").rstrip("/")
VOICE_PUBLIC_BASE = os.getenv("RECEPTION_VOICE_PUBLIC_BASE", "").rstrip("/")
# Browser-facing WS URL injected into the page.
BROWSER_VOICE_WS_URL = os.getenv("RECEPTION_BROWSER_VOICE_WS_URL", "").strip()
# Upstream WS URL used by the frontend proxy itself.
PROXY_VOICE_UPSTREAM_WS_URL = (
    os.getenv("RECEPTION_PROXY_UPSTREAM_WS_URL", "").strip()
    or os.getenv("RECEPTION_VOICE_PUBLIC_WS_URL", "").strip()
)

app = FastAPI(title="Reception Frontend", version="1.0.0")
app.mount("/app-assets", StaticFiles(directory=str(SCREEN_ROOT)), name="app-assets")
ASSET_VERSION = str(int(time.time()))
logger = logging.getLogger("reception_frontend")


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


def _derive_proxy_base(host: str, scheme: str, current_port: int, target_port: int) -> str:
    suffix = f"-{current_port}.proxy.runpod.net"
    if host.endswith(suffix):
        return f"{scheme}://{host[:-len(suffix)]}-{target_port}.proxy.runpod.net"
    if ":" in host:
        hostname, maybe_port = host.rsplit(":", 1)
        if maybe_port.isdigit():
            return f"{scheme}://{hostname}:{target_port}"
    return f"{scheme}://{host}"


def _runtime_config(request: Request) -> dict[str, str]:
    vision_http_base = VISION_PUBLIC_BASE or ""
    if BROWSER_VOICE_WS_URL:
        voice_ws_url = BROWSER_VOICE_WS_URL
    else:
        # Relative path keeps the browser on the actual public origin instead of
        # trusting the proxy-added Host header seen by FastAPI.
        voice_ws_url = "/voice-ws"
    return {
        "visionHttpBase": vision_http_base,
        "voiceWsUrl": voice_ws_url,
    }


def _inject_runtime_config(html_text: str, config: dict[str, str]) -> str:
    config_json = json.dumps(config, ensure_ascii=False)
    script = f'<script>window.RECEPTION_CONFIG = {config_json};</script>'
    live_js_tag = '<script src="/app-assets/live.js"></script>'
    if live_js_tag in html_text:
        return html_text.replace(live_js_tag, f"{script}\n  {live_js_tag}")
    return html_text.replace("</body>", f"  {script}\n</body>")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request) -> HTMLResponse:
    logger.info("[FRONTEND] GET / host=%s", request.headers.get("host", request.url.netloc))
    return await reception_page(request)


@app.get("/app", response_class=HTMLResponse)
async def app_page(request: Request) -> HTMLResponse:
    logger.info("[FRONTEND] GET /app host=%s", request.headers.get("host", request.url.netloc))
    return await reception_page(request)


@app.get("/reception", response_class=HTMLResponse)
async def reception_page(request: Request) -> HTMLResponse:
    config = _runtime_config(request)
    logger.info(
        "[FRONTEND] render path=%s host=%s asset_version=%s vision=%s voice_ws=%s",
        request.url.path,
        request.headers.get("host", request.url.netloc),
        ASSET_VERSION,
        config["visionHttpBase"],
        config["voiceWsUrl"],
    )
    html_text = _load_screen_html("live.html")
    html_text = _inject_runtime_config(html_text, config)
    return _html_response(html_text)


@app.get("/manual", response_class=HTMLResponse)
async def manual_page() -> HTMLResponse:
    logger.info("[FRONTEND] GET /manual asset_version=%s", ASSET_VERSION)
    return _html_response(_load_screen_html("index.html"))


@app.get("/app/manual", response_class=HTMLResponse)
async def app_manual_page() -> HTMLResponse:
    return await manual_page()


@app.websocket("/voice-ws")
async def voice_ws_proxy(websocket: WebSocket) -> None:
    client = websocket.client
    origin = websocket.headers.get("origin")
    logger.info("[FRONTEND_WS] incoming client=%s origin=%s", client, origin)
    await websocket.accept()
    try:
        import websockets
    except Exception:
        await websocket.close(code=1011)
        return

    upstream_base = VOICE_PUBLIC_BASE or f"http://127.0.0.1:{VOICE_PORT}"
    upstream_ws = PROXY_VOICE_UPSTREAM_WS_URL or upstream_base.replace("https://", "wss://").replace("http://", "ws://").rstrip("/") + "/ws"
    logger.info("[FRONTEND_WS] proxy client=%s -> upstream=%s", client, upstream_ws)

    try:
        async with websockets.connect(upstream_ws, max_size=None) as upstream:
            async def client_to_upstream() -> None:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        break
                    if message.get("bytes") is not None:
                        await upstream.send(message["bytes"])
                    elif message.get("text") is not None:
                        await upstream.send(message["text"])

            async def upstream_to_client() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            client_task = asyncio.create_task(client_to_upstream())
            upstream_task = asyncio.create_task(upstream_to_client())
            done, pending = await asyncio.wait({client_task, upstream_task}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    raise exc
    except WebSocketDisconnect:
        logger.info("[FRONTEND_WS] client disconnected client=%s", client)
        pass
    except Exception as exc:
        logger.exception("[FRONTEND_WS] proxy error client=%s upstream=%s error=%s", client, upstream_ws, exc)
        await websocket.close(code=1011)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger.info(
        "[FRONTEND] starting port=%s asset_version=%s screen_root=%s browser_voice_ws=%s proxy_upstream_ws=%s",
        FRONTEND_PORT,
        ASSET_VERSION,
        SCREEN_ROOT,
        BROWSER_VOICE_WS_URL or "/voice-ws",
        PROXY_VOICE_UPSTREAM_WS_URL or f"ws://127.0.0.1:{VOICE_PORT}/ws",
    )
    uvicorn.run(app, host="0.0.0.0", port=FRONTEND_PORT)
