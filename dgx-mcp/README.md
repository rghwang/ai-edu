# DGX 미디어 스택 — 운영 문서

아이들이 **Claude / ChatGPT 채팅창에서** DGX Spark로 영상·이미지·소리를 만들게 하는 MCP 서버와,
수업 때만 스택을 올렸다 내리는 운영 절차.

> **현재 상태 (2026-09-12): 전부 내려가 있음.** 평소에는 내려두고 수업 때만 올린다.
> 서비스가 뜬 채로 놀면 메모리 73G를 잡고 있고, 실제로 한 번 OOM으로 죽은 적이 있다.

---

## 1. 수업 운영 (이것만 알면 된다)

DGX에 `/home/rgh/services/dgx-mcp/class.sh` 가 있다. 저장소 원본은 `dgx-mcp/class.sh`.

```bash
# 수업 시작 30분 전
ssh aitopatom-27f6 '/home/rgh/services/dgx-mcp/class.sh up'
ssh aitopatom-27f6 '/home/rgh/services/dgx-mcp/class.sh warm'

# 수업 끝나고
ssh aitopatom-27f6 '/home/rgh/services/dgx-mcp/class.sh down'

# 아무 때나
ssh aitopatom-27f6 '/home/rgh/services/dgx-mcp/class.sh status'
```

**`warm` 을 빼먹지 말 것.** H3가 메모리에서 내려가 있으면 첫 컷이 **322초**,
워밍업해두면 **165초**다. 수업 중 아이들이 기다리는 시간이 두 배로 갈린다.

`up` 은 기동 순서를 지킨다 — `dgx-media` 의 health 는 `h3` 가 떠 있어야 200을 준다.

### 부팅 자동 기동은 꺼져 있다

`dgx-media.service` 와 `h3.service` 는 `disabled` 다. 재부팅해도 안 올라온다.
"수업 때만 띄운다"는 방침과 맞으므로 **그대로 둔다.**
(예전 부팅 로그에 `Found ordering cycle on vllm.service/stop` 문제가 있었는데, 이제 무관하다.)

---

## 2. 구조

```
아이 기기 (맥·아이패드)
   │  Claude / ChatGPT 채팅창
   ▼
Anthropic · OpenAI 클라우드          ← 여기서 우리 서버로 접속한다. 아이 기기가 아니다.
   │  MCP over HTTPS
   ▼
Tailscale Funnel :10000              ← 공개 노출. 아직 안 켬 (§5)
   ▼
mcp_server.py (127.0.0.1:8093)       ← 이 저장소
   │  Bearer = 아이의 H3 키
   ▼
litellm-admin 게이트웨이 (:4100/api/media)
   ▼
dgx-media.service (:8092)            ← 큐·메모리 예산 관리
   ├─ FLUX.2 Klein 4B      이미지
   ├─ Stable Audio 3       소리
   └─ h3.service (:8091)   MiniMax H3 영상
```

`443 → 4000`, `8443 → 4100` 은 기존 라우팅이다. **건드리지 않았다.**
MCP는 10000번 포트만 쓰므로 끄면 즉시 원복된다.

---

## 3. 왜 MCP인가 (그리고 언제 CLI인가)

맥·아이패드의 **Claude·ChatGPT 앱은 임의의 HTTP 호출을 못 한다.**
REST 주소와 키를 줘도 그 앱은 요청을 보낼 방법이 없다. 그래서 아이패드에서는 MCP가 유일한 길이다.

| | 터미널 있음 (맥 + Codex·Claude Code) | 터미널 없음 (아이패드, 채팅 앱만) |
|---|---|---|
| `dgx-media` CLI | **더 낫다** — 게이트웨이 제한시간 1시간이라 동기 호출이 그냥 되고, 결과 파일이 로컬에 떨어져 편집으로 직행 | 불가능 |
| MCP 커넥터 | 가능하지만 굳이 | **유일** |

---

## 4. 인증 — 계정이 없다. 키가 곧 신원이다

```
1. Claude/ChatGPT 가 스스로 앱 등록          OAuth DCR, 사람 개입 없음
2. 아이에게 /authorize 로그인 화면 → H3 키 입력
3. 서버가 그 키로 게이트웨이 /v1/queue 를 찔러 유효성 확인 (200/401)
4. 토큰 발급, 토큰에 키를 묶음
```

이후 모든 생성 요청이 그 아이의 키로 나가므로 **RPM 제한과 사용량 집계가 그대로 유지된다.**
Postgres `h3_keys` 를 직접 읽지 않는다 — DB 결합이 없다.
dgx-admin 에서 키를 회전시키면 그 토큰의 생성 요청이 401 로 막힌다.

OAuth 를 쓰는 이유는 로그인이 필요해서가 아니라, **커넥터 설정창에 키 입력칸이 없어서**다
(`static_headers` 는 조직 관리자 전용 베타). 로그인 화면이 키를 건네는 유일한 통로다.

- 무차별 대입 방어: 실패 **10회 / 10분 / IP**
- 토큰 유효기간 90일, 인증 코드 5분, PKCE S256 필수
- `owner` = `key-<sha256(키)[:10]>` — 키가 바뀌면 이전 작업 이력과는 끊긴다

---

## 5. 공개 노출 (아직 안 켬)

커넥터 주소로 쓸 것:

```
https://aitopatom-27f6.taildae05f.ts.net:10000/mcp
```

켜는 명령 — **사람이 직접 실행해야 한다** (에이전트 자동 승인이 막힌다):

```bash
sudo tailscale funnel --bg --https=10000 http://127.0.0.1:8093
```

끄기: `sudo tailscale funnel --https=10000 off`
직전 serve 설정 백업: `/home/rgh/services/dgx-mcp/serve-backup-*.json`

**이 주소는 공개 사이트(`connect.html`)에 적지 않는다.** 로그인 화면이 인터넷에 노출되므로
아이들에게 따로 알려준다. Anthropic 의 출발 IP 대역은 `160.79.104.0/21` 로 공개돼 있어,
더 조이고 싶으면 방화벽으로 그 대역만 허용할 수 있다.

---

## 6. 도구

모든 생성 도구는 **기다리지 않고 job_id 를 돌려준다.** 커넥터의 도구 호출 제한시간이
생성 시간(영상 약 165초)보다 짧기 때문이다.

| 도구 | 하는 일 |
|---|---|
| `make_video` | 세로 영상 한 컷 (512x768 · 6초 · 10스텝) |
| `make_image` | 그림 한 장 (FLUX.2 Klein) |
| `make_sound` | 배경음악·효과음 (Stable Audio 3) |
| `check_job` | 진행 상황. 앞에 몇 개 밀렸는지, 얼마나 남았는지 |
| `my_jobs` | 내가 만든 것 목록 |

큐 상태를 숨기지 않고 그대로 말해준다 — *"앞에 2개가 밀려 있다. 약 8분 15초 걸릴 것 같다."*
H3가 한 번에 하나씩만 만든다는 사실이 수업 재료가 된다(W18 'AI의 크기'와 연결).

`check_job` 은 예상 시간을 넘기면 **"약 0초 남았다"고 거짓말하지 않고** 사실대로 말한다.

결과물은 `GET /v/<view_token>` 으로 내려준다. 파일은 7일 뒤 자동 삭제.

---

## 7. 실측 (2026-09-12, 512x768 · 6초 · 10스텝)

| 상황 | 소요 |
|---|---:|
| 웜 (연속 3회) | **162 · 162 · 162초** |
| 콜드 (모델 로딩 포함) | 181초 |
| 오래 놀린 뒤 첫 컷 | **322초** |

영상은 **동시 1개**만 만들어진다(`limits_by_type.video = 1`). 4명이 동시에 걸어도 줄을 선다.
수업 설계에서 무너지는 건 "동시 생성"이 아니라 **작품을 4개로 쪼개는 것**이다.

메모리: 스택이 뜨면 119G 중 **73G 사용**, 내리면 19G.

---

## 8. 배포 / 갱신

```bash
# 서버 코드 갱신
scp dgx-mcp/mcp_server.py aitopatom-27f6:/home/rgh/services/dgx-mcp/
scp dgx-mcp/class.sh      aitopatom-27f6:/home/rgh/services/dgx-mcp/
ssh aitopatom-27f6 'pkill -f mcp_server.py; /home/rgh/services/dgx-mcp/class.sh up'

# 최초 1회 (이미 되어 있음)
python3 -m venv /home/rgh/services/dgx-mcp/.venv
/home/rgh/services/dgx-mcp/.venv/bin/pip install fastapi uvicorn httpx python-multipart
```

상태 파일: `/home/rgh/services/dgx-mcp/state.db` (sqlite — 클라이언트·토큰·작업),
결과물: `/home/rgh/services/dgx-mcp/out/`, 로그: `run.log`.

---

## 9. 아이용 설정 안내

저장소 루트 `connect.html` → https://rg-teach-ai.vercel.app/connect.html

맥·아이패드 × Claude·ChatGPT 네 경우를 탭으로 나눠 안내한다. 핵심 두 가지:

- **연결 추가는 웹에서만 된다.** 아이패드 앱에는 그 메뉴가 없다. 사파리로 붙이면 앱에 동기화된다.
- **ChatGPT는 유료 플랜(Plus 이상)** 에서만 개발자 모드가 켜진다. Claude는 무료도 1개 가능.

---

## 10. 남은 일

- [ ] Funnel 10000 켜기 (§5) — 사람이 직접 실행
- [ ] 아이별 키 발급 — 지금 `family-media` 위주라 아이별 사용량 구분이 안 된다
- [ ] CLI 경로 정리 여부 결정 — `tools/dgx-media.py` 공개 배포, `dgx-media/CLAUDE_CODE_*.md`,
      `connect.html` 하단 문단, `w16-slides.html`(드라마)의 CLI 기준 "촬영 거는 법" 슬라이드
- [ ] 실제 커넥터 연결 테스트 (claude.ai 에서 끝까지)

## 11. 검증해 둔 것

OAuth 전 구간을 실제로 돌려봤다 — DCR 201 · 로그인 폼 · **틀린 키 거부** · 올바른 키 302 ·
**PKCE 불일치 400** · 토큰 200 · initialize · tools/list · tools/call.
영상 생성도 도구로 끝까지 돌려 결과 URL이 `200 video/mp4 450KB` 를 주는 것까지 확인했다.
