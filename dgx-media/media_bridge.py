#!/usr/bin/env python3
"""Loopback-only DGX media bridge for FLUX images, Stable Audio, and H3 video."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response


IMAGE_MODEL_ID = os.environ.get("IMAGE_MODEL_ID", "black-forest-labs/FLUX.2-klein-4B")
IMAGE_READY_MARKER = Path(os.environ.get("IMAGE_READY_MARKER", "/home/rgh/services/flux2-klein-4b/.model-ready"))
SA3_RUNNER = Path(os.environ.get("SA3_RUNNER", "/home/rgh/services/stable-audio-3-medium/sa3_remote_runner.py"))
SA3_ENGINES = tuple(Path(path) for path in (
    "/home/rgh/services/stable-audio-3-medium/optimized/tensorRT/models/sm_121/t5gemma/t5gemma_fp16.trt",
    "/home/rgh/services/stable-audio-3-medium/optimized/tensorRT/models/sm_121/sa3-m/dit_fp16.trt",
    "/home/rgh/services/stable-audio-3-medium/optimized/tensorRT/models/sm_121/same-l/enc_dynamic_triton_swa.trt",
    "/home/rgh/services/stable-audio-3-medium/optimized/tensorRT/models/sm_121/same-l/dec_dynamic_triton_swa.trt",
))
H3_URL = os.environ.get("H3_URL", "http://127.0.0.1:8091").rstrip("/")
OUTPUT_ROOT = Path(os.environ.get("MEDIA_OUTPUT_ROOT", "/home/rgh/services/flux2-klein-4b/output"))
MAX_IMAGE_PIXELS = 1024 * 1024
FAMILY_SAFE_PREFIX = (
    "Family-friendly artwork suitable for children. No nudity, no sexual content, "
    "no graphic violence. "
)
BLOCKED_PROMPT = re.compile(
    r"\b(?:nsfw|nude|nudity|porn|pornographic|sexual|sexually|genitals?)\b|"
    r"(?:나체|누드|음란|포르노|성기|성적인)",
    re.IGNORECASE,
)

app = FastAPI(title="DGX Spark Media API", docs_url=None, redoc_url=None)
MEDIA_LOCK = asyncio.Lock()
IMAGE_PIPE: Any | None = None
IMAGE_LOAD_LOCK = asyncio.Lock()
log = logging.getLogger("dgx-media")


def _as_int(value: Any, name: str, default: int, minimum: int, maximum: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"{name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise HTTPException(400, f"{name} must be between {minimum} and {maximum}")
    return parsed


def _as_float(value: Any, name: str, default: float, minimum: float, maximum: float) -> float:
    if value in (None, ""):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"{name} must be a number") from exc
    if not minimum <= parsed <= maximum:
        raise HTTPException(400, f"{name} must be between {minimum} and {maximum}")
    return parsed


def _parse_size(raw: Any) -> tuple[int, int]:
    value = str(raw or "1024x1024").lower().strip()
    match = re.fullmatch(r"(\d{3,4})x(\d{3,4})", value)
    if not match:
        raise HTTPException(400, "size must look like 1024x1024")
    width, height = map(int, match.groups())
    if not (512 <= width <= 1536 and 512 <= height <= 1536):
        raise HTTPException(400, "image width and height must be between 512 and 1536")
    if width % 64 or height % 64:
        raise HTTPException(400, "image width and height must be multiples of 64")
    if width * height > MAX_IMAGE_PIXELS:
        raise HTTPException(400, "image canvas may not exceed 1,048,576 pixels")
    return width, height


def _safe_prompt(raw: Any) -> str:
    prompt = str(raw or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")
    if len(prompt) > 3000:
        raise HTTPException(400, "prompt must be 3000 characters or fewer")
    if BLOCKED_PROMPT.search(prompt):
        raise HTTPException(400, "this family media endpoint rejected unsafe prompt terms")
    return FAMILY_SAFE_PREFIX + prompt


def _load_image_pipe_sync() -> Any:
    global IMAGE_PIPE
    if IMAGE_PIPE is not None:
        return IMAGE_PIPE
    if not IMAGE_READY_MARKER.is_file():
        raise RuntimeError("FLUX image model is not fully installed")
    from diffusers import Flux2KleinPipeline

    log.info("loading image model %s", IMAGE_MODEL_ID)
    pipe = Flux2KleinPipeline.from_pretrained(
        IMAGE_MODEL_ID,
        dtype=torch.bfloat16,
        local_files_only=True,
    )
    pipe.enable_model_cpu_offload()
    pipe.set_progress_bar_config(disable=True)
    IMAGE_PIPE = pipe
    return pipe


async def _image_pipe() -> Any:
    if IMAGE_PIPE is not None:
        return IMAGE_PIPE
    async with IMAGE_LOAD_LOCK:
        return await asyncio.to_thread(_load_image_pipe_sync)


def _generate_image_sync(pipe: Any, payload: dict[str, Any]) -> tuple[bytes, int]:
    seed = _as_int(payload.get("seed"), "seed", secrets.randbelow(2**32), 0, 2**32 - 1)
    width, height = _parse_size(payload.get("size"))
    steps = _as_int(payload.get("num_inference_steps", payload.get("steps")), "steps", 4, 1, 12)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    result = pipe(
        prompt=_safe_prompt(payload.get("prompt")),
        width=width,
        height=height,
        guidance_scale=1.0,
        num_inference_steps=steps,
        generator=generator,
    )
    output = io.BytesIO()
    result.images[0].save(output, format="PNG", optimize=True)
    return output.getvalue(), seed


def _run_audio_sync(payload: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt or len(prompt) > 2000:
        raise HTTPException(400, "prompt must contain 1-2000 characters")
    request_payload = {
        "job_name": str(payload.get("name") or "media-api"),
        "tracks": [{
            "name": str(payload.get("name") or "track"),
            "prompt": prompt,
            "negative_prompt": str(payload.get("negative_prompt") or ""),
            "duration_seconds": _as_float(payload.get("duration_seconds"), "duration_seconds", 30.0, 3.0, 380.0),
            "steps": _as_int(payload.get("steps"), "steps", 8, 1, 50),
            "cfg": _as_float(payload.get("cfg"), "cfg", 1.0, 0.1, 10.0),
            "seed": _as_int(payload.get("seed"), "seed", secrets.randbelow(2**31 - 1), 0, 2**31 - 1),
        }],
    }
    completed = subprocess.run(
        [sys.executable, str(SA3_RUNNER)],
        input=json.dumps(request_payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        timeout=1800,
        check=False,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()[-800:]
        raise RuntimeError(f"Stable Audio generation failed: {detail}")
    result_line = next((line for line in completed.stdout.splitlines() if line.startswith("SA3_RESULT=")), None)
    if not result_line:
        raise RuntimeError("Stable Audio runner did not return a result")
    manifest = json.loads(result_line.removeprefix("SA3_RESULT="))
    track = manifest["tracks"][0]
    if not track.get("ok"):
        log_path = Path(track.get("log_path", ""))
        detail = log_path.read_text(encoding="utf-8", errors="replace").strip()[-800:] if log_path.is_file() else ""
        raise RuntimeError(detail or track.get("error") or "Stable Audio generation failed")
    path = Path(track["remote_path"]).resolve()
    if not path.is_file():
        raise RuntimeError("Stable Audio output file is missing")
    return path, manifest


@app.get("/health")
async def health() -> JSONResponse:
    video_ready = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            video_ready = (await client.get(f"{H3_URL}/health")).status_code == 200
    except httpx.RequestError:
        pass
    audio_ready = SA3_RUNNER.is_file() and all(path.is_file() and path.stat().st_size > 0 for path in SA3_ENGINES)
    ready = IMAGE_READY_MARKER.is_file() and audio_ready and video_ready
    return JSONResponse({
        "status": "ready" if ready else "starting",
        "ready": ready,
        "busy": MEDIA_LOCK.locked(),
        "image": {"model": IMAGE_MODEL_ID, "installed": IMAGE_READY_MARKER.is_file(), "loaded": IMAGE_PIPE is not None},
        "audio": {"model": "stable-audio-3-medium", "installed": audio_ready},
        "video": {"model": "minimax-h3-fl2va", "ready": video_ready},
    }, status_code=200 if ready else 503)


@app.get("/v1/models")
async def models() -> dict[str, Any]:
    return {"object": "list", "data": [
        {"id": "flux-2-klein-4b", "object": "model", "type": "image"},
        {"id": "stable-audio-3-medium", "object": "model", "type": "audio"},
        {"id": "minimax-h3-fl2va", "object": "model", "type": "video"},
    ]}


@app.post("/v1/images/generations")
async def generate_image(payload: dict[str, Any]) -> dict[str, Any]:
    if int(payload.get("n", 1)) != 1:
        raise HTTPException(400, "n must be 1 on this shared family endpoint")
    if str(payload.get("response_format", "b64_json")) != "b64_json":
        raise HTTPException(400, "response_format must be b64_json")
    started = time.monotonic()
    try:
        async with MEDIA_LOCK:
            pipe = await _image_pipe()
            image_bytes, seed = await asyncio.to_thread(_generate_image_sync, pipe, payload)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("image generation failed")
        raise HTTPException(500, f"image generation failed: {exc}") from exc
    return {
        "created": int(time.time()),
        "model": "flux-2-klein-4b",
        "seed": seed,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}],
    }


@app.post("/v1/audio/generations")
async def generate_audio(payload: dict[str, Any]) -> FileResponse:
    try:
        async with MEDIA_LOCK:
            output, manifest = await asyncio.to_thread(_run_audio_sync, payload)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("audio generation failed")
        raise HTTPException(500, f"audio generation failed: {exc}") from exc
    return FileResponse(
        output,
        media_type="audio/wav",
        filename=output.name,
        headers={"X-DGX-Job-ID": str(manifest["job_id"])},
    )


@app.post("/v1/videos/sync")
async def generate_video(request: Request) -> Response:
    body = await request.body()
    headers = {"content-type": request.headers.get("content-type", "application/json")}
    try:
        async with MEDIA_LOCK:
            async with httpx.AsyncClient(timeout=httpx.Timeout(3600.0, connect=20.0)) as client:
                upstream = await client.post(f"{H3_URL}/v1/videos/sync", content=body, headers=headers)
    except httpx.RequestError as exc:
        raise HTTPException(502, f"H3 video service connection failed: {exc}") from exc
    passthrough = {
        key: value for key, value in upstream.headers.items()
        if key.lower() in {"content-type", "content-disposition"}
    }
    return Response(content=upstream.content, status_code=upstream.status_code, headers=passthrough)
