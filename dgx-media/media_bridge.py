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
from contextlib import asynccontextmanager
from dataclasses import dataclass
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

GIB = 1024 ** 3
MEMORY_BUDGET_BYTES = int(float(os.environ.get("MEDIA_MEMORY_BUDGET_GIB", "44")) * GIB)
MIN_AVAILABLE_BYTES = int(float(os.environ.get("MEDIA_MIN_AVAILABLE_GIB", "12")) * GIB)
MAX_PARALLEL_JOBS = int(os.environ.get("MEDIA_MAX_PARALLEL_JOBS", "4"))
JOB_LIMITS = {
    "image": int(os.environ.get("MEDIA_IMAGE_MAX_JOBS", "1")),
    "audio": int(os.environ.get("MEDIA_AUDIO_MAX_JOBS", "4")),
    "video": int(os.environ.get("MEDIA_VIDEO_MAX_JOBS", "1")),
}
JOB_MEMORY_BYTES = {
    "image": int(float(os.environ.get("MEDIA_IMAGE_JOB_GIB", "14")) * GIB),
    "image_cold": int(float(os.environ.get("MEDIA_IMAGE_COLD_JOB_GIB", "30")) * GIB),
    "audio": int(float(os.environ.get("MEDIA_AUDIO_JOB_GIB", "8")) * GIB),
    "video": int(float(os.environ.get("MEDIA_VIDEO_JOB_GIB", "22")) * GIB),
}

app = FastAPI(title="DGX Spark Media API", docs_url=None, redoc_url=None)
IMAGE_PIPE: Any | None = None
IMAGE_LOAD_LOCK = asyncio.Lock()
IMAGE_RUN_LOCK = asyncio.Lock()
VIDEO_RUN_LOCK = asyncio.Lock()
log = logging.getLogger("dgx-media")


@dataclass
class JobTicket:
    id: str
    kind: str
    queued_at: float
    memory_bytes: int = 0
    started_at: float | None = None

    @property
    def queue_wait_seconds(self) -> float:
        end = self.started_at if self.started_at is not None else time.monotonic()
        return max(0.0, end - self.queued_at)


def _memory_info() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            name, raw = line.split(":", 1)
            values[name] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return {"total_bytes": 0, "available_bytes": 0}
    return {
        "total_bytes": values.get("MemTotal", 0),
        "available_bytes": values.get("MemAvailable", values.get("MemFree", 0)),
    }


def _job_memory(kind: str) -> int:
    if kind == "image" and IMAGE_PIPE is None:
        return JOB_MEMORY_BYTES["image_cold"]
    return JOB_MEMORY_BYTES[kind]


class MemoryScheduler:
    """Admit jobs by model limits, a reservation budget, and live available memory."""

    def __init__(self) -> None:
        self.condition = asyncio.Condition()
        self.waiting: list[JobTicket] = []
        self.active: dict[str, JobTicket] = {}

    def _active_kind_count(self, kind: str) -> int:
        return sum(ticket.kind == kind for ticket in self.active.values())

    def _reserved_bytes(self) -> int:
        return sum(ticket.memory_bytes for ticket in self.active.values())

    def _can_start(self, ticket: JobTicket) -> bool:
        required = _job_memory(ticket.kind)
        memory = _memory_info()
        if len(self.active) >= MAX_PARALLEL_JOBS:
            return False
        if self._active_kind_count(ticket.kind) >= JOB_LIMITS[ticket.kind]:
            return False
        if self._reserved_bytes() + required > MEMORY_BUDGET_BYTES:
            return False
        if memory["available_bytes"] and memory["available_bytes"] - required < MIN_AVAILABLE_BYTES:
            return False
        return True

    async def acquire(self, kind: str) -> JobTicket:
        ticket = JobTicket(id=f"{kind}_{secrets.token_urlsafe(8)}", kind=kind, queued_at=time.monotonic())
        async with self.condition:
            self.waiting.append(ticket)
            try:
                while not self._can_start(ticket):
                    await self.condition.wait()
            except BaseException:
                if ticket in self.waiting:
                    self.waiting.remove(ticket)
                self.condition.notify_all()
                raise
            self.waiting.remove(ticket)
            ticket.memory_bytes = _job_memory(kind)
            ticket.started_at = time.monotonic()
            self.active[ticket.id] = ticket
            self.condition.notify_all()
            return ticket

    async def release(self, ticket: JobTicket) -> None:
        async with self.condition:
            self.active.pop(ticket.id, None)
            self.condition.notify_all()

    @asynccontextmanager
    async def slot(self, kind: str):
        ticket = await self.acquire(kind)
        try:
            yield ticket
        finally:
            await self.release(ticket)

    async def snapshot(self) -> dict[str, Any]:
        async with self.condition:
            memory = _memory_info()
            active_counts = {kind: self._active_kind_count(kind) for kind in JOB_LIMITS}
            waiting_counts = {
                kind: sum(ticket.kind == kind for ticket in self.waiting)
                for kind in JOB_LIMITS
            }
            return {
                "policy": "memory-aware-parallel",
                "max_parallel_jobs": MAX_PARALLEL_JOBS,
                "active_jobs": len(self.active),
                "waiting_jobs": len(self.waiting),
                "active_by_type": active_counts,
                "waiting_by_type": waiting_counts,
                "limits_by_type": JOB_LIMITS,
                "memory": {
                    "total_bytes": memory["total_bytes"],
                    "total_gib": round(memory["total_bytes"] / GIB, 1),
                    "available_bytes": memory["available_bytes"],
                    "available_gib": round(memory["available_bytes"] / GIB, 1),
                    "minimum_available_bytes": MIN_AVAILABLE_BYTES,
                    "minimum_available_gib": round(MIN_AVAILABLE_BYTES / GIB, 1),
                    "reservation_budget_bytes": MEMORY_BUDGET_BYTES,
                    "reservation_budget_gib": round(MEMORY_BUDGET_BYTES / GIB, 1),
                    "active_reserved_bytes": self._reserved_bytes(),
                    "active_reserved_gib": round(self._reserved_bytes() / GIB, 1),
                    "reservation_remaining_bytes": max(0, MEMORY_BUDGET_BYTES - self._reserved_bytes()),
                    "reservation_remaining_gib": round(max(0, MEMORY_BUDGET_BYTES - self._reserved_bytes()) / GIB, 1),
                    "job_estimates_bytes": {
                        **JOB_MEMORY_BYTES,
                        "image_current": _job_memory("image"),
                    },
                },
                "active": [
                    {
                        "type": ticket.kind,
                        "running_seconds": round(time.monotonic() - (ticket.started_at or time.monotonic()), 1),
                        "reserved_bytes": ticket.memory_bytes,
                    }
                    for ticket in self.active.values()
                ],
                "waiting": [
                    {
                        "type": ticket.kind,
                        "waiting_seconds": round(ticket.queue_wait_seconds, 1),
                        "estimated_bytes": _job_memory(ticket.kind),
                    }
                    for ticket in self.waiting
                ],
            }


SCHEDULER = MemoryScheduler()


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
    scheduler = await SCHEDULER.snapshot()
    return JSONResponse({
        "status": "ready" if ready else "starting",
        "ready": ready,
        "busy": bool(scheduler["active_jobs"] or scheduler["waiting_jobs"]),
        "image": {
            "model": IMAGE_MODEL_ID,
            "installed": IMAGE_READY_MARKER.is_file(),
            "loaded": IMAGE_PIPE is not None,
            "active": scheduler["active_by_type"]["image"],
            "waiting": scheduler["waiting_by_type"]["image"],
        },
        "audio": {
            "model": "stable-audio-3-medium",
            "installed": audio_ready,
            "active": scheduler["active_by_type"]["audio"],
            "waiting": scheduler["waiting_by_type"]["audio"],
        },
        "video": {
            "model": "minimax-h3-fl2va",
            "ready": video_ready,
            "active": scheduler["active_by_type"]["video"],
            "waiting": scheduler["waiting_by_type"]["video"],
        },
        "scheduler": scheduler,
    }, status_code=200 if ready else 503)


@app.get("/v1/queue")
async def queue_status() -> dict[str, Any]:
    return await SCHEDULER.snapshot()


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
        async with SCHEDULER.slot("image") as ticket:
            async with IMAGE_RUN_LOCK:
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
        "queue_wait_seconds": round(ticket.queue_wait_seconds, 3),
        "data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}],
    }


@app.post("/v1/audio/generations")
async def generate_audio(payload: dict[str, Any]) -> FileResponse:
    try:
        async with SCHEDULER.slot("audio") as ticket:
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
        headers={
            "X-DGX-Job-ID": str(manifest["job_id"]),
            "X-DGX-Queue-Wait-Seconds": f"{ticket.queue_wait_seconds:.3f}",
        },
    )


@app.post("/v1/videos/sync")
async def generate_video(request: Request) -> Response:
    body = await request.body()
    headers = {"content-type": request.headers.get("content-type", "application/json")}
    try:
        async with SCHEDULER.slot("video") as ticket:
            async with VIDEO_RUN_LOCK:
                async with httpx.AsyncClient(timeout=httpx.Timeout(3600.0, connect=20.0)) as client:
                    upstream = await client.post(f"{H3_URL}/v1/videos/sync", content=body, headers=headers)
    except httpx.RequestError as exc:
        raise HTTPException(502, f"H3 video service connection failed: {exc}") from exc
    passthrough = {
        key: value for key, value in upstream.headers.items()
        if key.lower() in {"content-type", "content-disposition"}
    }
    passthrough["X-DGX-Queue-Wait-Seconds"] = f"{ticket.queue_wait_seconds:.3f}"
    return Response(content=upstream.content, status_code=upstream.status_code, headers=passthrough)
