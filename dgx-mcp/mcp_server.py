#!/usr/bin/env python3
"""우리 반 AI 컴퓨터 — MCP 서버.

아이들이 Claude / ChatGPT 채팅창에서 DGX Spark로 영상·이미지·소리를 만들게 한다.

인증: OAuth 2.1 (DCR + PKCE S256). 로그인 화면에서 아이가 자기 H3 키를 넣으면,
그 키로 기존 게이트웨이를 한 번 찔러 유효성을 확인하고 토큰에 묶는다.
이후 모든 생성 요청은 그 아이의 키로 나가므로 RPM 제한과 사용량 집계가 그대로 유지된다.

생성은 오래 걸린다(영상 약 165초). 커넥터의 도구 호출 제한시간을 넘기므로
모든 도구는 즉시 job_id를 돌려주고, 진행 상황은 check_job 으로 확인한다.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import queue
import secrets
import sqlite3
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

# ── 설정 ────────────────────────────────────────────────────────────────
PUBLIC_BASE = os.environ.get(
    "MCP_PUBLIC_BASE", "https://aitopatom-27f6.taildae05f.ts.net:10000"
).rstrip("/")
MEDIA_BASE = os.environ.get("MCP_MEDIA_BASE", "http://127.0.0.1:4100/api/media").rstrip("/")
STATE_DIR = Path(os.environ.get("MCP_STATE_DIR", "/home/rgh/services/dgx-mcp"))
DB_PATH = STATE_DIR / "state.db"
OUT_DIR = STATE_DIR / "out"

TOKEN_TTL = 60 * 60 * 24 * 90        # 90일 — 수업 중 다시 로그인하는 일이 없게
CODE_TTL = 300
JOB_KEEP = 60 * 60 * 24 * 7

VIDEO_DEFAULTS = {"width": 512, "height": 768, "seconds": 6, "steps": 10}
IMAGE_DEFAULTS = {"model": "flux-2-klein-4b", "size": "1024x1024", "steps": 4, "n": 1}
SOUND_DEFAULTS = {"steps": 8, "duration_seconds": 30.0}

# 실측(2026-09-12): 영상 웜 162초 · 콜드 181초 / 이미지 예열 후 약 108초
EST_SECONDS = {"video": 165, "image": 110, "sound": 40}

STATE_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── 저장소 ──────────────────────────────────────────────────────────────
_db_lock = threading.Lock()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _db_lock, db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS clients(
              client_id TEXT PRIMARY KEY, client_secret TEXT,
              redirect_uris TEXT NOT NULL, name TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS codes(
              code TEXT PRIMARY KEY, client_id TEXT, redirect_uri TEXT,
              challenge TEXT, media_key TEXT, owner TEXT, expires REAL);
            CREATE TABLE IF NOT EXISTS tokens(
              token TEXT PRIMARY KEY, refresh TEXT, client_id TEXT,
              media_key TEXT, owner TEXT, expires REAL, created REAL);
            CREATE TABLE IF NOT EXISTS jobs(
              job_id TEXT PRIMARY KEY, kind TEXT, owner TEXT, media_key TEXT,
              label TEXT, status TEXT, detail TEXT, filename TEXT,
              view_token TEXT, created REAL, started REAL, finished REAL);
            CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner, created);
            """
        )


def q1(sql: str, args: tuple = ()) -> sqlite3.Row | None:
    with _db_lock, db() as conn:
        cur = conn.execute(sql, args)
        return cur.fetchone()


def qall(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    with _db_lock, db() as conn:
        return list(conn.execute(sql, args))


def run(sql: str, args: tuple = ()) -> None:
    with _db_lock, db() as conn:
        conn.execute(sql, args)
        conn.commit()


# ── 미디어 게이트웨이 호출 ────────────────────────────────────────────────
def media_probe(key: str) -> bool:
    """아이가 넣은 키가 유효한지 기존 게이트웨이로 확인한다."""
    try:
        r = httpx.get(
            f"{MEDIA_BASE}/v1/queue",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
        )
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def multipart(fields: dict[str, str]) -> tuple[bytes, str]:
    """dgx-media CLI 와 같은 형식의 multipart 본문을 만든다."""
    boundary = f"----dgxmcp{secrets.token_hex(16)}"
    out: list[bytes] = []
    for name, value in fields.items():
        out.append(f"--{boundary}\r\n".encode())
        out.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        out.append(f"{value}\r\n".encode())
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def media_call(kind: str, key: str, payload: dict) -> tuple[bytes, str]:
    """생성 요청. (바이트, 확장자)를 돌려준다. 게이트웨이 제한시간은 1시간."""
    auth = {"Authorization": f"Bearer {key}"}
    timeout = httpx.Timeout(3600.0, connect=20.0)

    if kind == "video":
        # H3는 multipart/form-data 로 받는다 (dgx-media CLI 와 같은 형식).
        body, ctype = multipart(
            {
                "prompt": payload["prompt"],
                "width": str(payload["width"]),
                "height": str(payload["height"]),
                "num_inference_steps": str(payload["steps"]),
                "extra_params": json.dumps(
                    {"task": "t2va", "duration": payload["seconds"], "audio_flow_shift": 3}
                ),
            }
        )
        r = httpx.post(
            f"{MEDIA_BASE}/v1/videos/sync",
            headers={**auth, "Content-Type": ctype},
            content=body,
            timeout=timeout,
        )
        if r.status_code != 200:
            raise RuntimeError(f"생성 실패 ({r.status_code}): {r.text[:300]}")
        return r.content, "mp4"

    if kind == "sound":
        r = httpx.post(
            f"{MEDIA_BASE}/v1/audio/generations", headers=auth, json=payload, timeout=timeout
        )
        if r.status_code != 200:
            raise RuntimeError(f"생성 실패 ({r.status_code}): {r.text[:300]}")
        return r.content, "wav"

    r = httpx.post(
        f"{MEDIA_BASE}/v1/images/generations", headers=auth, json=payload, timeout=timeout
    )
    if r.status_code != 200:
        raise RuntimeError(f"생성 실패 ({r.status_code}): {r.text[:300]}")
    items = r.json().get("data") or []
    if not items or not items[0].get("b64_json"):
        raise RuntimeError("응답에 이미지 데이터가 없습니다")
    return base64.b64decode(items[0]["b64_json"]), "png"


# ── 작업 큐 ─────────────────────────────────────────────────────────────
QUEUES: dict[str, queue.Queue] = {k: queue.Queue() for k in ("video", "image", "sound")}
WORKERS = {"video": 1, "image": 1, "sound": 2}
PENDING: dict[str, list[str]] = {k: [] for k in QUEUES}
_pending_lock = threading.Lock()


def enqueue(kind: str, job_id: str) -> int:
    with _pending_lock:
        PENDING[kind].append(job_id)
        pos = len(PENDING[kind])
    QUEUES[kind].put(job_id)
    return pos


def queue_position(kind: str, job_id: str) -> int | None:
    with _pending_lock:
        if job_id in PENDING[kind]:
            return PENDING[kind].index(job_id) + 1
    return None


def worker(kind: str) -> None:
    while True:
        job_id = QUEUES[kind].get()
        row = q1("SELECT * FROM jobs WHERE job_id=?", (job_id,))
        if row is None:
            QUEUES[kind].task_done()
            continue
        run("UPDATE jobs SET status='running', started=? WHERE job_id=?", (time.time(), job_id))
        try:
            payload = json.loads(row["detail"] or "{}")
            blob, ext = media_call(kind, row["media_key"], payload)
            fname = f"{job_id}.{ext}"
            (OUT_DIR / fname).write_bytes(blob)
            run(
                "UPDATE jobs SET status='done', filename=?, detail=?, finished=? WHERE job_id=?",
                (fname, json.dumps({"bytes": len(blob)}), time.time(), job_id),
            )
        except Exception as exc:  # noqa: BLE001 — 실패 사유를 아이에게 그대로 보여준다
            run(
                "UPDATE jobs SET status='error', detail=?, finished=? WHERE job_id=?",
                (json.dumps({"error": str(exc)[:500]}), time.time(), job_id),
            )
        finally:
            with _pending_lock:
                if job_id in PENDING[kind]:
                    PENDING[kind].remove(job_id)
            QUEUES[kind].task_done()


# ── OAuth ──────────────────────────────────────────────────────────────
def now() -> float:
    return time.time()


def new_id(n: int = 24) -> str:
    return secrets.token_urlsafe(n)


def verify_pkce(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=") == challenge


def bearer_of(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def session_of(request: Request) -> sqlite3.Row | None:
    token = bearer_of(request)
    if not token:
        return None
    row = q1("SELECT * FROM tokens WHERE token=?", (token,))
    if row is None or row["expires"] < now():
        return None
    return row


def unauthorized() -> JSONResponse:
    return JSONResponse(
        {"error": "unauthorized"},
        status_code=401,
        headers={
            "WWW-Authenticate": (
                f'Bearer resource_metadata="{PUBLIC_BASE}'
                f'/.well-known/oauth-protected-resource"'
            )
        },
    )


app = FastAPI(title="우리 반 AI 컴퓨터 MCP")


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "base": PUBLIC_BASE}


@app.get("/.well-known/oauth-protected-resource")
@app.get("/.well-known/oauth-protected-resource/mcp")
async def prm() -> dict:
    return {
        "resource": f"{PUBLIC_BASE}/mcp",
        "authorization_servers": [PUBLIC_BASE],
        "scopes_supported": ["media"],
        "bearer_methods_supported": ["header"],
    }


@app.get("/.well-known/oauth-authorization-server")
@app.get("/.well-known/oauth-authorization-server/mcp")
@app.get("/.well-known/openid-configuration")
async def asm() -> dict:
    return {
        "issuer": PUBLIC_BASE,
        "authorization_endpoint": f"{PUBLIC_BASE}/authorize",
        "token_endpoint": f"{PUBLIC_BASE}/token",
        "registration_endpoint": f"{PUBLIC_BASE}/register",
        "scopes_supported": ["media"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
    }


@app.post("/register")
async def register(request: Request) -> JSONResponse:
    body = await request.json()
    redirects = body.get("redirect_uris") or []
    if not isinstance(redirects, list) or not redirects:
        return JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)
    client_id = new_id(18)
    run(
        "INSERT INTO clients(client_id, client_secret, redirect_uris, name, created)"
        " VALUES(?,?,?,?,?)",
        (client_id, None, json.dumps(redirects), body.get("client_name") or "", now()),
    )
    return JSONResponse(
        {
            "client_id": client_id,
            "redirect_uris": redirects,
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "client_id_issued_at": int(now()),
        },
        status_code=201,
    )


LOGIN_PAGE = """<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>우리 반 AI 컴퓨터 · 로그인</title>
<style>
 :root{{--paper:#f6efe1;--card:#fffaf0;--ink:#23201a;--soft:#5a5347;--line:#d8cbb1;--clay:#bd5a32;--deep:#9c4622;--teal:#3f6b63}}
 *{{box-sizing:border-box;margin:0;padding:0}}
 body{{font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',sans-serif;background:var(--paper);
   color:var(--ink);line-height:1.7;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:22px}}
 .card{{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:30px 26px;max-width:430px;width:100%}}
 .eyebrow{{font-size:.72rem;letter-spacing:.22em;text-transform:uppercase;color:var(--deep);font-weight:700}}
 h1{{font-size:1.45rem;line-height:1.3;margin-top:10px;font-weight:800}}
 p.lead{{color:var(--soft);font-size:.93rem;margin-top:10px}}
 label{{display:block;font-weight:700;font-size:.9rem;margin-top:22px}}
 input{{width:100%;margin-top:8px;padding:13px 14px;font-size:1rem;border:1.5px solid var(--line);
   border-radius:11px;background:#fff;font-family:ui-monospace,monospace}}
 input:focus{{outline:2px solid var(--teal);outline-offset:1px;border-color:var(--teal)}}
 button{{width:100%;margin-top:18px;padding:14px;font-size:1rem;font-weight:700;color:#fff;
   background:var(--clay);border:0;border-radius:11px;cursor:pointer}}
 button:hover{{background:var(--deep)}}
 .app{{margin-top:16px;padding:11px 13px;background:#fbf0e6;border:1px dashed var(--clay);
   border-radius:10px;font-size:.85rem;color:var(--soft)}}
 .err{{margin-top:16px;padding:11px 13px;background:#fdecec;border:1px solid #e7b4b4;
   border-radius:10px;font-size:.88rem;color:#8c2f2f}}
 .tip{{margin-top:18px;font-size:.82rem;color:var(--soft)}}
</style></head><body>
<div class="card">
  <div class="eyebrow">우리 반 AI 컴퓨터</div>
  <h1>내 키로 로그인</h1>
  <p class="lead">선생님에게 받은 <b>내 키</b>를 붙여넣으면 연결이 끝난다.
     이 키는 나만 쓰는 것이고, 채팅창에는 넣지 않는다.</p>
  <div class="app">연결하려는 앱 · <b>{client}</b></div>
  {error}
  <form method="post">
    <input type="hidden" name="rid" value="{rid}">
    <label for="key">내 키</label>
    <input id="key" name="key" type="password" autocomplete="off"
           autocapitalize="none" autocorrect="off" spellcheck="false"
           placeholder="선생님에게 받은 키" required>
    <button type="submit">연결하기</button>
  </form>
  <p class="tip">키가 안 맞는다고 나오면, 앞뒤에 빈칸이 딸려왔는지 확인하고 다시 복사해 보자.</p>
</div></body></html>"""

PENDING_AUTH: dict[str, dict] = {}

# 로그인 화면은 인터넷에 열려 있다. 키 무차별 대입을 막는다.
FAIL_WINDOW = 600
FAIL_LIMIT = 10
_fails: dict[str, list[float]] = {}
_fail_lock = threading.Lock()


def too_many_fails(ip: str) -> bool:
    with _fail_lock:
        recent = [t for t in _fails.get(ip, []) if t > now() - FAIL_WINDOW]
        _fails[ip] = recent
        return len(recent) >= FAIL_LIMIT


def note_fail(ip: str) -> None:
    with _fail_lock:
        _fails.setdefault(ip, []).append(now())


def render_login(rid: str, client_name: str, error: str = "") -> HTMLResponse:
    err_html = f'<div class="err">{html.escape(error)}</div>' if error else ""
    return HTMLResponse(
        LOGIN_PAGE.format(
            rid=html.escape(rid),
            client=html.escape(client_name or "알 수 없는 앱"),
            error=err_html,
        )
    )


@app.get("/authorize")
async def authorize(request: Request) -> Response:
    p = request.query_params
    client_id = p.get("client_id", "")
    redirect_uri = p.get("redirect_uri", "")
    challenge = p.get("code_challenge", "")
    method = p.get("code_challenge_method", "")
    state = p.get("state", "")

    client = q1("SELECT * FROM clients WHERE client_id=?", (client_id,))
    if client is None:
        return HTMLResponse("<h1>알 수 없는 앱입니다</h1>", status_code=400)
    if redirect_uri not in json.loads(client["redirect_uris"]):
        return HTMLResponse("<h1>돌아갈 주소가 등록돼 있지 않습니다</h1>", status_code=400)
    if method != "S256" or not challenge:
        return HTMLResponse("<h1>PKCE(S256)가 필요합니다</h1>", status_code=400)

    rid = new_id(12)
    PENDING_AUTH[rid] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "challenge": challenge,
        "state": state,
        "expires": now() + CODE_TTL,
        "name": client["name"],
    }
    return render_login(rid, client["name"])


@app.post("/authorize")
async def authorize_submit(
    request: Request, rid: str = Form(...), key: str = Form(...)
) -> Response:
    req = PENDING_AUTH.get(rid)
    if req is None or req["expires"] < now():
        PENDING_AUTH.pop(rid, None)
        return HTMLResponse("<h1>시간이 지났습니다. 앱에서 다시 연결해 주세요.</h1>", status_code=400)

    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or (request.client.host if request.client else "?"))
    if too_many_fails(ip):
        return render_login(
            rid, req["name"], "키를 너무 여러 번 틀렸습니다. 10분 뒤에 다시 해주세요."
        )

    media_key = key.strip()
    if not media_probe(media_key):
        note_fail(ip)
        return render_login(rid, req["name"], "키가 맞지 않습니다. 다시 확인해 주세요.")

    owner = f"key-{hashlib.sha256(media_key.encode()).hexdigest()[:10]}"
    code = new_id(24)
    run(
        "INSERT INTO codes(code, client_id, redirect_uri, challenge, media_key, owner, expires)"
        " VALUES(?,?,?,?,?,?,?)",
        (code, req["client_id"], req["redirect_uri"], req["challenge"],
         media_key, owner, now() + CODE_TTL),
    )
    PENDING_AUTH.pop(rid, None)

    sep = "&" if "?" in req["redirect_uri"] else "?"
    url = f"{req['redirect_uri']}{sep}code={urllib.parse.quote(code)}"
    if req["state"]:
        url += f"&state={urllib.parse.quote(req['state'])}"
    return RedirectResponse(url, status_code=302)


def issue_tokens(client_id: str, media_key: str, owner: str) -> dict:
    token, refresh = new_id(32), new_id(32)
    run(
        "INSERT INTO tokens(token, refresh, client_id, media_key, owner, expires, created)"
        " VALUES(?,?,?,?,?,?,?)",
        (token, refresh, client_id, media_key, owner, now() + TOKEN_TTL, now()),
    )
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": TOKEN_TTL,
        "refresh_token": refresh,
        "scope": "media",
    }


@app.post("/token")
async def token_endpoint(request: Request) -> JSONResponse:
    form = await request.form()
    grant = form.get("grant_type")

    if grant == "authorization_code":
        row = q1("SELECT * FROM codes WHERE code=?", (form.get("code", ""),))
        if row is None or row["expires"] < now():
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        run("DELETE FROM codes WHERE code=?", (row["code"],))
        if row["redirect_uri"] != form.get("redirect_uri"):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        if not verify_pkce(form.get("code_verifier", ""), row["challenge"]):
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        return JSONResponse(issue_tokens(row["client_id"], row["media_key"], row["owner"]))

    if grant == "refresh_token":
        row = q1("SELECT * FROM tokens WHERE refresh=?", (form.get("refresh_token", ""),))
        if row is None:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        run("DELETE FROM tokens WHERE token=?", (row["token"],))
        return JSONResponse(issue_tokens(row["client_id"], row["media_key"], row["owner"]))

    return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)


# ── 결과물 내려주기 ──────────────────────────────────────────────────────
@app.get("/v/{view_token}")
async def view(view_token: str) -> Response:
    row = q1("SELECT * FROM jobs WHERE view_token=? AND status='done'", (view_token,))
    if row is None or not row["filename"]:
        return HTMLResponse("<h1>없는 영상입니다</h1>", status_code=404)
    path = OUT_DIR / row["filename"]
    if not path.is_file():
        return HTMLResponse("<h1>파일이 지워졌습니다</h1>", status_code=404)
    ext = path.suffix.lstrip(".")
    ctype = {"mp4": "video/mp4", "png": "image/png", "wav": "audio/wav"}.get(
        ext, "application/octet-stream"
    )
    return Response(
        path.read_bytes(),
        media_type=ctype,
        headers={"Content-Disposition": f'inline; filename="{row["label"] or path.name}.{ext}"'},
    )


# ── MCP 도구 ────────────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "make_video",
        "description": (
            "우리 반 AI 컴퓨터(MiniMax H3)로 한국어 대사가 들어간 세로 영상을 한 컷 만든다. "
            "한 컷에 약 2분 45초 걸리고 한 번에 하나씩만 만들어지므로, 이 도구는 기다리지 않고 "
            "바로 job_id를 돌려준다. 결과는 check_job 으로 확인한다. "
            "프롬프트에는 인물·장소·화면 크기·연기·정확한 대사·소리를 순서대로 적는다. "
            "한 화면에 말하는 사람은 한 명, 대사는 한 문장만."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "촬영 지시문(한국어). 인물·장소·화면·연기·대사·소리."},
                "label": {"type": "string", "description": "이 컷의 이름. 예: take-A1"},
                "seconds": {"type": "integer", "minimum": 3, "maximum": 10, "description": "길이(초). 기본 6."},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "make_image",
        "description": (
            "우리 반 AI 컴퓨터(FLUX.2 Klein)로 그림을 한 장 만든다. 약 2분 걸리므로 "
            "바로 job_id를 돌려준다. 결과는 check_job 으로 확인한다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "그림 설명"},
                "label": {"type": "string", "description": "이름"},
                "size": {"type": "string", "description": "가로x세로. 64의 배수, 기본 1024x1024"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "make_sound",
        "description": (
            "우리 반 AI 컴퓨터(Stable Audio 3)로 배경음악이나 효과음을 만든다. "
            "바로 job_id를 돌려주고, 결과는 check_job 으로 확인한다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "소리 설명"},
                "label": {"type": "string", "description": "이름"},
                "seconds": {"type": "number", "minimum": 3, "maximum": 380, "description": "길이(초). 기본 30."},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "check_job",
        "description": (
            "만들고 있는 것이 다 됐는지 확인한다. 아직이면 앞에 몇 개가 밀려 있고 "
            "얼마나 더 걸리는지 알려준다. 다 됐으면 볼 수 있는 주소를 준다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
    {
        "name": "my_jobs",
        "description": "내가 오늘 만든 것들의 목록과 상태를 보여준다.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def fmt_wait(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"약 {seconds}초"
    return f"약 {seconds // 60}분 {seconds % 60}초"


def start_job(kind: str, sess: sqlite3.Row, label: str, payload: dict) -> str:
    job_id = new_id(10)
    run(
        "INSERT INTO jobs(job_id, kind, owner, media_key, label, status, detail,"
        " view_token, created) VALUES(?,?,?,?,?,?,?,?,?)",
        (job_id, kind, sess["owner"], sess["media_key"], label, "queued",
         json.dumps(payload), new_id(16), now()),
    )
    pos = enqueue(kind, job_id)
    ahead = pos - 1
    wait = fmt_wait(pos * EST_SECONDS[kind])
    front = "바로 시작한다" if ahead == 0 else f"앞에 {ahead}개가 밀려 있다"
    return (
        f"걸었다. job_id = {job_id} ({label})\n"
        f"{front}. 다 되기까지 {wait} 걸릴 것 같다.\n"
        f"check_job 으로 확인하면 된다. 그동안 다음 컷 프롬프트를 다듬어 두자."
    )


def job_report(row: sqlite3.Row) -> str:
    label = row["label"] or row["job_id"]
    if row["status"] == "done":
        url = f"{PUBLIC_BASE}/v/{row['view_token']}"
        took = int((row["finished"] or 0) - (row["started"] or 0))
        return (
            f"{label} — 다 됐다! ({took}초 걸림)\n{url}\n\n"
            "합격 검사를 하자: 대사가 정확한가 · 끝말이 잘리지 않았나 · "
            "얼굴과 옷이 그대로인가 · 화면에 글자가 생기지 않았나."
        )
    if row["status"] == "error":
        detail = json.loads(row["detail"] or "{}")
        return f"{label} — 실패했다.\n{detail.get('error', '알 수 없는 이유')}"
    if row["status"] == "running":
        elapsed = now() - (row["started"] or now())
        left = EST_SECONDS[row["kind"]] - elapsed
        if left > 5:
            return f"{label} — 지금 만들고 있다. {fmt_wait(left)} 남았다."
        # 예상을 넘겼다. 0초라고 거짓말하지 말고 사실대로 말한다.
        return (
            f"{label} — 아직 만들고 있다. 예상보다 조금 더 걸리는 중 "
            f"(지금까지 {fmt_wait(elapsed)}).\n"
            "오랜만에 쓰면 준비하는 데 시간이 더 든다. 조금만 더 기다려 보자."
        )
    pos = queue_position(row["kind"], row["job_id"])
    if pos is None:
        return f"{label} — 순서를 기다리고 있다."
    ahead = pos - 1
    front = "바로 시작한다" if ahead == 0 else f"앞에 {ahead}개"
    return f"{label} — 기다리는 중. {front}, {fmt_wait(pos * EST_SECONDS[row['kind']])} 남았다."


def call_tool(name: str, args: dict, sess: sqlite3.Row) -> str:
    if name == "make_video":
        label = args.get("label") or "take"
        payload = dict(VIDEO_DEFAULTS)
        payload["prompt"] = args["prompt"]
        if args.get("seconds"):
            payload["seconds"] = int(args["seconds"])
        return start_job("video", sess, label, payload)

    if name == "make_image":
        label = args.get("label") or "image"
        payload = dict(IMAGE_DEFAULTS)
        payload["prompt"] = args["prompt"]
        if args.get("size"):
            payload["size"] = args["size"]
        return start_job("image", sess, label, payload)

    if name == "make_sound":
        label = args.get("label") or "sound"
        payload = dict(SOUND_DEFAULTS)
        payload["prompt"] = args["prompt"]
        payload["name"] = label
        if args.get("seconds"):
            payload["duration_seconds"] = float(args["seconds"])
        return start_job("sound", sess, label, payload)

    if name == "check_job":
        row = q1(
            "SELECT * FROM jobs WHERE job_id=? AND owner=?",
            (args.get("job_id", ""), sess["owner"]),
        )
        if row is None:
            return "그런 job_id가 없다. my_jobs 로 목록을 확인해 보자."
        return job_report(row)

    if name == "my_jobs":
        rows = qall(
            "SELECT * FROM jobs WHERE owner=? ORDER BY created DESC LIMIT 20",
            (sess["owner"],),
        )
        if not rows:
            return "아직 만든 게 없다."
        return "\n\n".join(job_report(r) for r in rows)

    raise ValueError(f"모르는 도구: {name}")


# ── MCP 엔드포인트 (JSON-RPC over HTTP) ───────────────────────────────────
SUPPORTED_PROTOCOLS = ["2025-11-25", "2025-06-18", "2025-03-26"]


def rpc_result(rid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def rpc_error(rid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle_rpc(msg: dict, sess: sqlite3.Row) -> dict | None:
    method = msg.get("method")
    rid = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        want = params.get("protocolVersion")
        version = want if want in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[1]
        return rpc_result(
            rid,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "우리 반 AI 컴퓨터", "version": "1.0.0"},
                "instructions": (
                    "DGX Spark로 영상·그림·소리를 만든다. 영상은 한 컷에 약 2분 45초 걸리고 "
                    "한 번에 하나씩만 만들어진다. make_* 도구는 기다리지 않고 job_id를 돌려주니, "
                    "check_job 으로 확인하라. 아이와 대화 중이라면 기다리는 동안 "
                    "다음 컷 프롬프트를 다듬도록 도와라."
                ),
            },
        )

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None

    if method == "ping":
        return rpc_result(rid, {})

    if method == "tools/list":
        return rpc_result(rid, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        try:
            text = call_tool(name, args, sess)
            return rpc_result(rid, {"content": [{"type": "text", "text": text}]})
        except Exception as exc:  # noqa: BLE001 — 도구 오류는 모델이 읽고 고치게 한다
            return rpc_result(
                rid,
                {"content": [{"type": "text", "text": f"오류: {exc}"}], "isError": True},
            )

    if method in ("resources/list", "prompts/list"):
        key = "resources" if method.startswith("resources") else "prompts"
        return rpc_result(rid, {key: []})

    return rpc_error(rid, -32601, f"지원하지 않는 method: {method}")


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> Response:
    sess = session_of(request)
    if sess is None:
        return unauthorized()

    body = await request.json()
    if isinstance(body, list):
        out = [r for r in (handle_rpc(m, sess) for m in body) if r is not None]
        return JSONResponse(out) if out else Response(status_code=202)

    result = handle_rpc(body, sess)
    if result is None:
        return Response(status_code=202)
    return JSONResponse(result)


@app.get("/mcp")
async def mcp_get(request: Request) -> Response:
    if session_of(request) is None:
        return unauthorized()
    return Response(status_code=405, headers={"Allow": "POST"})


@app.delete("/mcp")
async def mcp_delete(request: Request) -> Response:
    if session_of(request) is None:
        return unauthorized()
    return Response(status_code=204)


# ── 청소 ────────────────────────────────────────────────────────────────
def janitor() -> None:
    while True:
        time.sleep(3600)
        cutoff = now() - JOB_KEEP
        for row in qall("SELECT * FROM jobs WHERE created < ?", (cutoff,)):
            if row["filename"]:
                (OUT_DIR / row["filename"]).unlink(missing_ok=True)
        run("DELETE FROM jobs WHERE created < ?", (cutoff,))
        run("DELETE FROM codes WHERE expires < ?", (now(),))
        run("DELETE FROM tokens WHERE expires < ?", (now(),))


@app.on_event("startup")
async def startup() -> None:
    init_db()
    for kind, count in WORKERS.items():
        for _ in range(count):
            threading.Thread(target=worker, args=(kind,), daemon=True).start()
    threading.Thread(target=janitor, daemon=True).start()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("MCP_PORT", "8093")))
