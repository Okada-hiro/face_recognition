# Two-Machine Reception

`reception_main.py` and the one-machine scripts stay as-is. These files are only for the two-machine split.

## Layout

- Machine A: vision + frontend
  - `8000` `recognition.runpod_recognition_browser`
  - `8005` `application/reception_frontend.py`
- Machine B: voice
  - `8002` `lab_voice_talk/recognition_gate_main.py`

Browser entrypoint:

- `https://<machine-a>-8005.proxy.runpod.net/app`

## Machine B

```bash
cd /workspace/face_recognition
source .venv/bin/activate
export VOICE_PORT=8002
export QWEN3_REF_AUDIO=/workspace/face_recognition/lab_voice_talk/ref_audio.WAV
export QWEN3_REF_TEXT="$(cat /workspace/face_recognition/lab_voice_talk/ref_text.txt)"
bash run_two_machine_voice.sh
```

## Machine A

```bash
cd /workspace/face_recognition
source .venv/bin/activate
export RECOGNITION_VOICE_TALK_WS_URL="wss://<machine-b>-8002.proxy.runpod.net/ws"
export RECEPTION_BROWSER_VOICE_WS_URL="wss://<machine-b>-8002.proxy.runpod.net/ws"
export RECEPTION_VISION_PUBLIC_BASE="https://<machine-a>-8000.proxy.runpod.net"
unset RECOGNITION_VOICE_TALK_NOTIFY_BASE
unset RECOGNITION_VOICE_TALK_HTTP_BASE
bash run_two_machine_vision.sh
```

## Notes

- In the two-machine setup, the browser connects directly to the voice machine websocket.
- Preferred: the browser forwards `approached/left` events to Machine B over the existing voice websocket.
- `RECOGNITION_VOICE_TALK_NOTIFY_BASE` is optional now. Leave it empty unless you explicitly want server-to-server HTTP notifications.
- If you want the browser to use the frontend proxy instead, set `RECEPTION_BROWSER_VOICE_WS_URL="/voice-ws"` and set `RECEPTION_PROXY_UPSTREAM_WS_URL` on Machine A.
