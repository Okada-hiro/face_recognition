import argparse
import hashlib
import json
import os
import time
import wave
from pathlib import Path

import parallel_faster_text_to_speech as tts


TARGET_SR = int(tts.DEFAULT_PARAMS["target_sr"])


def write_pcm16_wav(path: Path, pcm_bytes: bytes, sample_rate: int = TARGET_SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)


def duration_sec_from_pcm(pcm_bytes: bytes, sample_rate: int = TARGET_SR) -> float:
    return len(pcm_bytes) / 2 / sample_rate


def pcm_digest(pcm_bytes: bytes) -> str:
    return hashlib.sha1(pcm_bytes).hexdigest()[:12]


def synth_nonstream(text: str, worker_id: int | None) -> bytes:
    if worker_id is None:
        return tts.synthesize_speech_to_memory(text)
    return tts.synthesize_speech_to_memory_for_worker(text, worker_id)


def synth_stream(text: str, worker_id: int | None) -> tuple[bytes, int]:
    if worker_id is None:
        chunk_iter = tts.synthesize_speech_to_memory_stream(text)
    else:
        chunk_iter = tts.synthesize_speech_to_memory_stream_for_worker(text, worker_id)
    parts = []
    chunk_count = 0
    for pcm_chunk in chunk_iter:
        if not pcm_chunk:
            continue
        parts.append(pcm_chunk)
        chunk_count += 1
    return b"".join(parts), chunk_count


def run_mode(mode: str, text: str, repeats: int, worker_id: int | None, out_dir: Path) -> list[dict]:
    rows = []
    for i in range(1, repeats + 1):
        t0 = time.perf_counter()
        if mode == "nonstream":
            pcm_bytes = synth_nonstream(text, worker_id)
            chunk_count = None
        elif mode == "stream":
            pcm_bytes, chunk_count = synth_stream(text, worker_id)
        else:
            raise ValueError(f"unknown mode: {mode}")

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if not pcm_bytes:
            row = {
                "mode": mode,
                "run": i,
                "ok": False,
                "elapsed_ms": round(elapsed_ms, 1),
                "chunk_count": chunk_count,
                "duration_sec": 0.0,
                "bytes": 0,
                "sha1": None,
                "wav_path": None,
            }
        else:
            wav_path = out_dir / mode / f"run_{i:02d}.wav"
            write_pcm16_wav(wav_path, pcm_bytes)
            row = {
                "mode": mode,
                "run": i,
                "ok": True,
                "elapsed_ms": round(elapsed_ms, 1),
                "chunk_count": chunk_count,
                "duration_sec": round(duration_sec_from_pcm(pcm_bytes), 3),
                "bytes": len(pcm_bytes),
                "sha1": pcm_digest(pcm_bytes),
                "wav_path": str(wav_path),
            }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
    return rows


def summarize(rows: list[dict]) -> dict:
    ok_rows = [row for row in rows if row["ok"]]
    if not ok_rows:
        return {
            "runs": len(rows),
            "ok_runs": 0,
            "min_duration_sec": None,
            "max_duration_sec": None,
            "unique_sha1": 0,
        }
    durations = [row["duration_sec"] for row in ok_rows]
    return {
        "runs": len(rows),
        "ok_runs": len(ok_rows),
        "min_duration_sec": min(durations),
        "max_duration_sec": max(durations),
        "unique_sha1": len({row["sha1"] for row in ok_rows}),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Qwen3-TTS non-streaming and streaming output for the same text.",
    )
    parser.add_argument("--text", required=True, help="Text to synthesize repeatedly.")
    parser.add_argument("--repeats", type=int, default=10, help="Number of runs per mode.")
    parser.add_argument("--worker-id", type=int, default=1, help="Worker id to use. Set 0 to use default model.")
    parser.add_argument(
        "--out-dir",
        default=os.path.join("incoming_audio", "qwen3_repro"),
        help="Directory to store generated wav files and summary.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    worker_id = None if args.worker_id == 0 else args.worker_id
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "text": args.text,
        "repeats": args.repeats,
        "worker_id": worker_id,
        "out_dir": str(out_dir),
        "qwen3_model_path": tts.QWEN3_MODEL_PATH,
        "qwen3_min_new_tokens": tts.QWEN3_MIN_NEW_TOKENS,
        "qwen3_max_new_tokens_cap": tts.QWEN3_MAX_NEW_TOKENS_CAP,
        "qwen3_new_tokens_per_char": tts.QWEN3_NEW_TOKENS_PER_CHAR,
        "qwen3_ascii_new_tokens_per_char": getattr(tts, "QWEN3_ASCII_NEW_TOKENS_PER_CHAR", None),
        "qwen3_space_new_tokens": getattr(tts, "QWEN3_SPACE_NEW_TOKENS", None),
        "qwen3_ascii_punct_new_tokens": getattr(tts, "QWEN3_ASCII_PUNCT_NEW_TOKENS", None),
    }
    print(json.dumps({"config": config}, ensure_ascii=False))

    all_rows = []
    for mode in ("nonstream", "stream"):
        print(json.dumps({"phase": "start", "mode": mode}, ensure_ascii=False))
        rows = run_mode(mode, args.text, args.repeats, worker_id, out_dir)
        summary = summarize(rows)
        print(json.dumps({"phase": "summary", "mode": mode, **summary}, ensure_ascii=False))
        all_rows.extend(rows)

    summary_path = out_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "config": config,
                "summary": {
                    "nonstream": summarize([row for row in all_rows if row["mode"] == "nonstream"]),
                    "stream": summarize([row for row in all_rows if row["mode"] == "stream"]),
                },
                "rows": all_rows,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(json.dumps({"phase": "done", "summary_path": str(summary_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
