# 우리 반 AI 컴퓨터 — MCP 서버

아이들이 **Claude / ChatGPT 채팅창에서** DGX Spark로 영상·이미지·소리를 만들게 한다.
아이패드처럼 터미널이 없는 기기에서도 쓸 수 있다는 것이 `dgx-media` CLI 와의 차이다.

## 왜 MCP인가

맥·아이패드의 Claude·ChatGPT 앱은 임의의 HTTP 호출을 하지 못한다.
REST 주소와 키를 줘도 그 앱은 요청을 보낼 방법이 없다.
터미널이 있는 곳(Codex·Claude Code)에서는 `dgx-media` CLI 가 더 낫다 —
게이트웨이 제한시간이 1시간이라 동기 호출이 그대로 되고 결과가 로컬에 떨어진다.

## 인증

계정 시스템이 없다. **키가 곧 신원이다.**

1. Claude/ChatGPT 가 스스로 앱 등록 (OAuth DCR)
2. 아이에게 `/authorize` 로그인 화면 → 자기 H3 키 입력
3. 서버가 그 키로 기존 게이트웨이(`/v1/queue`)를 찔러 유효성 확인
4. 토큰 발급, 토큰에 키를 묶음

이후 모든 생성 요청은 그 아이의 키로 나가므로 **RPM 제한과 사용량 집계가 그대로 유지된다.**
Postgres `h3_keys` 를 직접 읽지 않는다. 키를 회전시키면 그 토큰의 생성 요청이 401 로 막힌다.

OAuth 를 쓰는 이유는 로그인이 필요해서가 아니라, 커넥터 설정창에 키 입력칸이 없어서다
(`static_headers` 는 조직 관리자 전용 베타). 로그인 화면이 키를 건네는 유일한 통로다.

무차별 대입 방어: 실패 10회 / 10분 / IP.

## 도구

모든 생성 도구는 **기다리지 않고 job_id 를 돌려준다.** 커넥터의 도구 호출 제한시간이
생성 시간(영상 약 165초)보다 짧기 때문이다.

| 도구 | 하는 일 |
|---|---|
| `make_video` | 세로 영상 한 컷 (512x768 · 6초 · 10스텝) |
| `make_image` | 그림 한 장 (FLUX.2 Klein) |
| `make_sound` | 배경음악·효과음 (Stable Audio 3) |
| `check_job` | 진행 상황. 앞에 몇 개 밀렸는지, 얼마나 남았는지 |
| `my_jobs` | 내가 만든 것 목록 |

큐 상태를 그대로 보여준다 — "앞에 2개가 밀려 있다. 약 8분 15초 걸릴 것 같다".
H3 가 한 번에 하나씩만 만든다는 사실을 숨기지 않는다.

## 실측 (2026-09-12, 512x768 · 6초 · 10스텝)

- 웜: **162초** (3회 연속 162/162초)
- 콜드(모델 로딩 포함): 181초
- 오래 놀린 뒤 첫 컷: **322초** — 수업 전 워밍업 권장

## 배포

```bash
# DGX
mkdir -p /home/rgh/services/dgx-mcp/out
python3 -m venv /home/rgh/services/dgx-mcp/.venv
/home/rgh/services/dgx-mcp/.venv/bin/pip install fastapi uvicorn httpx python-multipart
scp mcp_server.py aitopatom-27f6:/home/rgh/services/dgx-mcp/

# 내부 기동 (127.0.0.1:8093)
cd /home/rgh/services/dgx-mcp && .venv/bin/python mcp_server.py

# 공개 노출 (사람이 직접 실행)
sudo tailscale funnel --bg --https=10000 http://127.0.0.1:8093
```

커넥터 주소: `https://aitopatom-27f6.taildae05f.ts.net:10000/mcp`

443(→4000)·8443(→4100) 라우팅은 건드리지 않는다. 10000 번 포트만 쓰므로
`tailscale funnel --https=10000 off` 로 즉시 원복된다.

설정 안내 페이지는 저장소 루트의 `connect.html`.
