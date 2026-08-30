#!/usr/bin/env python3
"""Zero-dependency client for the authenticated DGX family media endpoint."""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import mimetypes
import os
import secrets
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_BASE_URL = "https://aitopatom-27f6.taildae05f.ts.net:8443/api/media"
CONFIG_PATH = Path.home() / ".config" / "dgx-media" / "config.json"


def load_config() -> dict[str, str]:
    config: dict[str, str] = {}
    if CONFIG_PATH.is_file():
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["base_url"] = os.environ.get("DGX_MEDIA_BASE_URL", config.get("base_url", DEFAULT_BASE_URL)).rstrip("/")
    config["api_key"] = os.environ.get("DGX_MEDIA_API_KEY", config.get("api_key", ""))
    return config


def save_config(base_url: str, api_key: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps({"base_url": base_url.rstrip("/"), "api_key": api_key}, indent=2) + "\n",
        encoding="utf-8",
    )
    CONFIG_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(f"설정 저장: {CONFIG_PATH} (권한 600)")


def request(path: str, *, payload: dict | None = None, body: bytes | None = None, content_type: str = "application/json"):
    config = load_config()
    if not config["api_key"]:
        raise SystemExit("API 키가 없습니다. 먼저 `dgx-media setup`을 실행하세요.")
    data = body if body is not None else (json.dumps(payload).encode("utf-8") if payload is not None else None)
    req = urllib.request.Request(
        config["base_url"] + path,
        data=data,
        headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": content_type},
        method="POST" if data is not None else "GET",
    )
    try:
        return urllib.request.urlopen(req, timeout=3700)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"DGX 요청 실패 ({exc.code}): {detail[:1000]}") from exc


def multipart(fields: dict[str, str], file_path: Path | None = None) -> tuple[bytes, str]:
    boundary = "----dgxmedia" + secrets.token_hex(12)
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"), b"\r\n",
        ])
    if file_path is not None:
        mime = mimetypes.guess_type(file_path.name)[0] or "image/png"
        parts.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="input_reference"; filename="{file_path.name}"\r\n'.encode(),
            f"Content-Type: {mime}\r\n\r\n".encode(),
            file_path.read_bytes(), b"\r\n",
        ])
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def main() -> int:
    parser = argparse.ArgumentParser(prog="dgx-media", description="DGX Spark 이미지·음악·영상 생성")
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="접속 주소와 키 저장")
    setup.add_argument("--base-url", default=DEFAULT_BASE_URL)
    setup.add_argument("--key", help="비권장: 명령 기록에 키가 남을 수 있음")
    sub.add_parser("status", help="세 모델 준비 상태 확인")

    image = sub.add_parser("image", help="FLUX 이미지 생성")
    image.add_argument("prompt")
    image.add_argument("-o", "--output", default="dgx-image.png")
    image.add_argument("--size", default="1024x1024")
    image.add_argument("--steps", type=int, default=4)
    image.add_argument("--seed", type=int)

    audio = sub.add_parser("audio", help="Stable Audio 음악·효과음 생성")
    audio.add_argument("prompt")
    audio.add_argument("-o", "--output", default="dgx-audio.wav")
    audio.add_argument("--seconds", type=float, default=30)
    audio.add_argument("--steps", type=int, default=8)
    audio.add_argument("--cfg", type=float, default=1.0)
    audio.add_argument("--seed", type=int)
    audio.add_argument("--negative-prompt", default="")

    video = sub.add_parser("video", help="MiniMax H3 대사 포함 영상 생성")
    video.add_argument("prompt")
    video.add_argument("-o", "--output", default="dgx-video.mp4")
    video.add_argument("--width", type=int, default=512)
    video.add_argument("--height", type=int, default=768)
    video.add_argument("--seconds", type=float, default=6)
    video.add_argument("--steps", type=int, default=10)
    video.add_argument("--seed", type=int)
    video.add_argument("--reference", type=Path)

    args = parser.parse_args()
    if args.command == "setup":
        key = args.key or getpass.getpass("DGX media API key (입력 숨김): ").strip()
        if not key:
            raise SystemExit("API 키가 비어 있습니다.")
        save_config(args.base_url, key)
        return 0
    if args.command == "status":
        with request("/health") as response:
            print(json.dumps(json.load(response), ensure_ascii=False, indent=2))
        return 0
    if args.command == "image":
        payload = {"model": "flux-2-klein-4b", "prompt": args.prompt, "size": args.size, "steps": args.steps, "n": 1}
        if args.seed is not None:
            payload["seed"] = args.seed
        with request("/v1/images/generations", payload=payload) as response:
            result = json.load(response)
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(base64.b64decode(result["data"][0]["b64_json"]))
        print(json.dumps({"output": str(output), "model": result["model"], "seed": result["seed"], "elapsed_seconds": result["elapsed_seconds"]}, ensure_ascii=False))
        return 0
    if args.command == "audio":
        payload = {"prompt": args.prompt, "duration_seconds": args.seconds, "steps": args.steps, "cfg": args.cfg, "negative_prompt": args.negative_prompt}
        if args.seed is not None:
            payload["seed"] = args.seed
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with request("/v1/audio/generations", payload=payload) as response:
            output.write_bytes(response.read())
        print(json.dumps({"output": str(output)}, ensure_ascii=False))
        return 0
    if args.command == "video":
        fields = {
            "prompt": args.prompt,
            "width": str(args.width),
            "height": str(args.height),
            "num_inference_steps": str(args.steps),
            "extra_params": json.dumps({"task": "fl2va" if args.reference else "t2va", "duration": args.seconds, "audio_flow_shift": 3}),
        }
        if args.seed is not None:
            fields["seed"] = str(args.seed)
        body, content_type = multipart(fields, args.reference)
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with request("/v1/videos/sync", body=body, content_type=content_type) as response:
            output.write_bytes(response.read())
        print(json.dumps({"output": str(output)}, ensure_ascii=False))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
