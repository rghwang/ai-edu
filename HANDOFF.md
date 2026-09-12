# 인수인계 (HANDOFF) — 우리 교실 AI 수업 사이트

다른 AI 에이전트(예: Codex)가 이 프로젝트를 이어서 작업할 수 있도록 정리한 문서. **작업 전에 이 문서를 먼저 읽으세요.**

---

## 0. 한 줄 요약
개인이 자녀·지인(초등학생·중학생 + 성인 1명) 대상으로 **매주 일요일 2시간 AI 교육**을 진행하며, 그 **진행 현황과 수업 자료**를 공유하는 **빌드 없는 정적 HTML 사이트**. 매주 수업이 끝나면 해당 주차를 '완료'로 옮기고 다음 주차 자료를 추가하는 식으로 계속 갱신한다.

- 로컬: `/Users/rgh/dev/ai-edu`
- 원격: `git@github.com:rghwang/ai-edu.git` (개인 GitHub 계정, **SSH**로 push)
- 라이브: **https://rg-teach-ai.vercel.app** (Vercel, GitHub push 시 자동 배포)

---

## 1. 배포 워크플로 (제일 중요)
- **빌드 없음.** 순수 정적 HTML. `main`에 push하면 **Vercel이 자동 재배포**.
- 표준 절차:
  ```bash
  cd /Users/rgh/dev/ai-edu
  git add -A && git commit -m "..." && git push
  ```
- **git 신원은 반드시 개인 이메일**: `user.name=rghwang`, `user.email=rghwang@live.com`. **회사 이메일 쓰지 말 것.**
- 커밋 메시지 말미에 공동작성 트레일러를 쓰던 관례가 있으나 필수는 아님.
- **배포 검증**: push 후 ~수십 초 뒤 라이브 확인. CDN 캐시 우회로 커밋 해시를 쿼리에 붙여 확인:
  ```bash
  H=$(git rev-parse --short HEAD)
  curl -s -o /dev/null -w '%{http_code}\n' "https://rg-teach-ai.vercel.app/index.html?v=$H"
  ```
  배포 직후 잠깐은 옛 버전이 잡힐 수 있으니, 특정 문구가 뜰 때까지 짧게 폴링(최대 ~2분)하면 확실하다.
- **주의**: 브라우저에 옛 버전이 캐시될 수 있음 → 사용자에게 "안 바뀌면 ⌘+Shift+R" 안내.

---

## 2. 페이지 구조
| 파일 | 내용 |
|---|---|
| `index.html` | **현황 대시보드(첫 화면).** 진행률 바 + '지금까지 해온 것'(past) + '앞으로의 커리큘럼'(phase1/phase2) + '메이커 루프' 섹션. 데이터는 하단 `<script>`의 배열, 상태·메모는 localStorage. |
| `vision.html` | 비전 & 커리큘럼(6가지 역량, 교육 원칙, 주간 리듬, 커리큘럼 표 W6~W15). 1·2단계 구분 없음. |
| `gemini.html` | Gemini 이미지·영상 + Google Flow(영상) + 구글 드라이브 저장 **교사 가이드**. |
| `deploy.html` | GitHub·Vercel·Claude Code(웹) **공용 계정 사전 세팅 가이드**(교사용). |
| `w6.html`~`w10.html` (+ `-slides.html`) | 각 주차 상세 수업안 + 학생 슬라이드. |
| `w8-anim.html`(+slides) | W8 2부(애니). W8은 1부 웹툰(`w8.html`)+2부 애니. |
| `w1-slides.html`~`w5-slides.html` | 완료 초기 수업(W1~W5) 학생 슬라이드(수업안 없음). |
| `w11~w19-slides.html` | W11~W19 학생 슬라이드(수업안 없음). W14 멀티플레이, W15 자기소개서, W16 H3 드라마, W17 에이전트, W18 AI의 크기, W19 한붓그리기. |
| `join.html` | W14 멀티플레이 게임 **아이용 참여 가이드**(Codex·Claude Code 복붙 프롬프트). |
| `connect.html` | 아이용 **MCP 커넥터 연결 안내**(맥·아이패드 × Claude·ChatGPT 4탭). 커넥터 주소는 공개 노출을 피해 페이지에 적지 않는다. |
| `dgx-mcp/` | DGX 미디어 스택 **운영 문서·MCP 서버·`class.sh`**. 수업 전후 기동/정지 절차는 여기. |
| `dgx-media/` | DGX 미디어 **서버 소스**(`media_bridge.py`, systemd 유닛)와 CLI 안내 문서. |
| `examples/lego-heritage-dogam.pdf` | W7 도감 예시(교사가 보여줌). |
| `README.md` | (구버전 설명이 남아 있음 — 이 HANDOFF가 최신) |

> **파일명 = 표시 주차번호 규칙.** 예: `w6.html`은 화면에 "W6"으로 뜬다. (초기에 w1/w2였던 걸 git mv로 맞춤.) 새 주차 자료는 `wN.html` + `wN-slides.html` 패턴.


---

## 3. 커리큘럼 현황 (2026-09 기준)
전체 **W1~W19**, 매주 완료되면 대시보드에서 past로 이동.

**완료(W1~W14) — index.html의 `past` 배열, '지금까지 해온 것':**
- W1 AI개념+게임(병합) / W2 음악 / W3 일상앱(투두) / W4 방탈출 / W5 파일·폴더
- W6 이미지·영상 맛보기+고르기 / W7 관심사 도감 슬라이드 / W8 미래의 나 웹툰→애니(1·2부) / W9 원래 AI로 안 하던 걸 AI로(써먹기) / W10 혼자 굴리는 힘+AI에게 잘 시키기 / W11 토큰·사용량
- W12 내 컴퓨터 밖으로(서버·업로드·배포 + 아케이드 커넥터) / W13 게임을 출품작으로(Codex 실전)
- W14 같은 세계에서 만나기(GitHub·Vercel·Supabase 멀티플레이, `join.html` 참여 가이드)

**예정(W15~W19) — `phase1` 배열, '앞으로의 커리큘럼':**
- **W15 자기소개서를 내 손으로** — 영재교육원 자기소개서 세 문항(소프트웨어·책 소감·저자에게 할 질문)을 각 200자로 **본인이** 쓴다. 양식에 "다른 사람이 대신 작성하는 경우 합격이 취소될 수 있다"고 명시돼 있어, AI는 **인터뷰어·거울·심사위원** 역할만 하고 글은 쓰지 않는다. 접수·전형료·교사추천서 체크리스트까지. (서울교대 인공지능영재교육원 접수 2026-09-14~16에 맞춰 급히 끼워 넣은 수업)
- W16 세로 드라마 만들기 — MiniMax H3 + DGX Spark. 한 팀·한 작품·4줄. **컷당 약 2분 45초(실측)**, 여덟 컷을 한꺼번에 큐에 걸어 GPU를 놀리지 않는다. 촬영석(컴퓨터 2대)/모니터(아이패드 2대) 역할 분리.
- W17 AI 에이전트 — 챗봇 vs 에이전트, 목표·규칙·완료기준, 안전, 자유 과제.
- W18 AI의 크기 — 파라미터·메모리·GPU·학습데이터·로컬 모델. 블라인드 비교.
- W19 정말 안 되는 걸까(한붓그리기) — 쾨니히스베르크 다리. 다음 주부터 매 수업 첫 15분 사고력 루틴 시작.

> **주차 번호는 바뀐다.** 급한 수업이 끼어들면 이후 주차를 한 칸씩 민다(파일명 `git mv` + 파일 안 `W<n>` 표기 + `index.html` 배열을 함께 고칠 것). 2026-09에 W15 자기소개서가 끼면서 드라마 이하가 한 칸씩 밀렸다.

---

## 4. 대시보드(index.html) 데이터 모델
하단 `<script>` 안:
- `past` = 완료 항목. 스키마 `{id, wk, title, note, tag, tagText, links?}`. `tag`는 `good`/`fix`/`base`, `links`는 `[{label, href}]`(선택).
- `phase1`, `phase2` = 예정 커리큘럼. 스키마 `{id, wk, skill, desc, mission, links?}`. (단계 구분은 없앴고 둘 다 연속으로 렌더됨. 보통 phase1에 몰아넣고 phase2=[].)
- **상태 저장**: localStorage 키 `aiclass_progress_v1` (브라우저별). `load()`에서 **past는 항상 'done'으로 강제**(과거 저장값 무시), phase는 기본 'todo'.
- `id`는 localStorage 키라 함부로 바꾸지 말 것(바꾸면 저장된 상태와 어긋남). 완료 이동 시 같은 id로 past에 옮기면 됨.

**흔한 작업 — 수업 완료 처리**: 해당 주차 객체를 `phase1`에서 빼서 `past` 끝에 추가(스키마를 past용 title/note/tag/tagText로 변환, links 유지). 그리고 '앞으로의 커리큘럼' 섹션 제목(`sec-head`)의 주차 범위 문구 갱신. `vision.html` 표는 그대로 두거나 필요 시 갱신.

---

## 5. 디자인 시스템 (일관성 유지 필수)
- 색 토큰: `--paper:#f6efe1; --paper-2:#efe5d2; --card:#fffaf0; --ink:#23201a; --ink-soft:#5a5347; --line:#d8cbb1; --clay:#bd5a32; --clay-deep:#9c4622; --amber:#d8973a; --teal:#3f6b63; --teal-soft:#e4ece8;`
- 폰트: 제목 **Hahmlet**(serif), 본문 **IBM Plex Sans KR**. (슬라이드의 코드/프롬프트류엔 Space Mono 보조 사용 가능.)
- 배경: paper + 은은한 radial-gradient(amber/teal).
- 새 페이지·슬라이드는 이 토큰/폰트를 그대로 재사용. 기존 `w9-slides.html`(점 네비형)·`w10-slides.html`을 복붙 베이스로 쓰면 편함.

### 학생 슬라이드 두 가지 네비 유형(둘 다 허용)
1. **사이트 제작형(W1~W10 slides)**: 상단 점(dots) + 하단 원형 ‹/›버튼 + 카운터, 클릭=다음, `.home` 링크. `.stage/.slide.active` 페이드.
2. **첨부 재작성형(W11~W15)**: 상단 진행 bar + 우하단 카운터 + 좌/우 클릭·키보드·터치. 원본(첨부)의 nav를 유지하고 **스타일만** warm으로 바꾼 것. W13·W14는 같은 네비 유형으로 새로 작성.

---

## 6. 도구 분담 (고정 원칙)
- **수업용 텍스트·리서치·코딩 프로토타입 = Claude** (W1~W5 Claude Code, W9 써먹기, W10 잘 시키기, W12 커넥터/배포). 공용 **Claude 계정**(18세 미만은 본인 계정 불가 → 교사/공용 계정 공유), 아이패드는 **claude.ai/code(웹) 브라우저**.
- **출품판 통합·자산 적용·테스트·배포 = Codex** (W13 실제 사례). 아케이드 결과물을 독립 프로젝트로 가져와 ImageGen 그래픽, 외부 DGX 음악, 모바일/게임 검수, Vercel·GitHub까지 한 작업 흐름으로 다룸.
- **일반 이미지·영상 창작 = Gemini / Google Flow(Veo)** (W6·W7·W8, `gemini.html`). **한국어 대사 드라마 = MiniMax H3 / DGX Spark** (W16). H3는 한 화면 한 화자·한 줄씩 생성하고, 네이티브 대사와 인물 연속성을 통과한 움직이는 테이크만 편집한다.
- 도감·슬라이드 결과물 = 구글 슬라이드. 학생 작업물 저장 = **교육용 계정 구글 드라이브 공유 폴더**.
- 계정: 이미지·영상용 **Google AI Pro**(교육용 gmail, 성인 계정) / 배포·코딩용 **Claude Pro**(개인·교육용, 회사 계정 아님). Family Link 대신 **공용 계정 로그인** 방식.
- 배포 스택: 클래스 공용 **GitHub + Vercel**(자동배포) — 설정 절차는 `deploy.html` 참고.
- **DGX 생성물(이미지·소리·영상) 접근**: 맥 터미널은 `dgx-media` CLI, 아이패드·채팅 앱은 **MCP 커넥터**(`connect.html`). 서비스는 평소 내려두고 수업 때만 올린다 — `dgx-mcp/README.md`.

---

## 7. 관례 / 주의사항
- **대상 라벨은 "초등학생 · 중학생"**(예전 "초4·중2"/"초등 고학년" 아님). 성인 참여자는 문구에 별도 병기.
- **완료 슬라이드는 항상 완료 표시**(§4 참조) — 옛 localStorage 잔재로 '예정' 보이는 문제를 코드에서 강제 처리해둠.
- 슬라이드의 수치(토큰량, Flow 크레딧, 요금제 등)는 **자주 바뀜** → 단정하지 말고 "계속 바뀜/계정에서 확인"으로. 수업 전 최신치만 점검.
- **첨부로 새 슬라이드가 오면** 대개 짙은 남색(Pretendard/Space Mono) 테마다. **본문 마크업·네비는 그대로 두고 `<style>` 블록만 warm 팔레트로 교체**하는 방식으로 사이트 톤에 맞춘다(§8).

---

## 8. 첨부 다크 슬라이드 → 사이트 톤 변환 레시피
`w11~w15-slides.html`가 이 네비 유형과 warm 톤을 사용한다. 첨부 다크 슬라이드는 파이썬(`/Users/rgh/miniconda3/bin/python3`)으로 `<style>...</style>`만 통째로 warm CSS로 치환하고, 폰트 링크(Pretendard→Hahmlet+IBM Plex+Space Mono)를 바꾸고, `<body>` 뒤에 `<a class="home" href="index.html">현황판 ↗</a>`를 삽입한다. 클래스명(eyebrow, card, grid, ul.plain, chips, turns, gates, ladder, prompt, flow/step, banner, kicker 등)은 **그대로 두고** warm 색으로 재정의만 하면 본문을 안 건드려도 된다. (기존 커밋의 파이썬 스니펫을 참고하거나 git 로그에서 찾을 것.)

색 매핑: coral→clay(`--clay`), cyan→teal, yellow→gold(`#a9761a` 텍스트)/amber(채움), 배경 다크→paper.

---

## 9. 검증 체크리스트 (커밋 전)
```bash
# index.html 스크립트 문법
node -e "const fs=require('fs');const m=fs.readFileSync('index.html','utf8').match(/<script>([\s\S]*)<\/script>/);new Function(m[1]);console.log('JS OK')"
# 내부 링크 깨짐 확인
for f in $(grep -ohE 'href=\"[a-z0-9/-]+\.(html|pdf)\"' *.html | sed 's/href=\"//;s/\"//' | sort -u); do [ -f \"$f\" ] || echo \"MISSING: $f\"; done
# 대시보드 주차 순서
grep -oE \"wk:'W[0-9]+'\" index.html | sed \"s/[^0-9]//g\" | sort -n | tr '\\n' ' '
```

---

## 10. 관련 프로젝트
- **우리반 아케이드** (`class-arcade.vercel.app`) — 아이들 게임 공유 갤러리. W12에서 AI **커넥터(MCP)** 로 게임을 업로드한 대상. 커넥터 주소: `class-arcade.vercel.app/api/mcp`, 직접 업로드: `class-arcade.vercel.app/upload`. (별도 저장소/프로젝트)
- **죽어야 이기는 용사 출품판** (`/Users/rgh/dev/openai-game-builers/death-knight`, `death-knight-web.vercel.app`) — W13 실제 사례. Codex 작업 제목은 `제출 버전 통합`.
- **DGX Spark** (`aitopatom-27f6`) — 이미지(FLUX.2 Klein)·소리(Stable Audio 3)·영상(MiniMax H3) 생성용 외부 AI 컴퓨터. **평소에는 서비스를 내려둔다** — 놀면 메모리 73G를 잡고 한 번 OOM으로 죽은 적이 있다. 수업 때만 `class.sh up` → `warm` → (끝나고) `down`. **운영 문서는 `dgx-mcp/README.md`** 를 볼 것. 두 가지 접근 경로가 있다: 터미널이 있는 맥은 `dgx-media` CLI(`tools/dgx-media.py`), 터미널이 없는 아이패드는 **MCP 커넥터**(`dgx-mcp/mcp_server.py`, 아이용 안내는 `connect.html`). 채팅 앱은 임의 HTTP 호출을 못 하므로 아이패드에서는 MCP가 유일한 길이다. 키·로컬 설정 파일은 저장소에 넣지 않는다. H3 제작 규칙은 `/Users/rgh/.codex/skills/dgx-h3-web-drama/SKILL.md` 참조.

---

## 11. Codex(또는 다른 에이전트)로 넘어갈 때 확인할 것
1. `/Users/rgh/dev/ai-edu`에서 작업. `git remote -v`가 위 SSH 주소인지, `git config user.email`이 `rghwang@live.com`인지 확인.
2. SSH 키(`~/.ssh/id_ed25519`)로 push됨(이미 GitHub 등록됨). push 안 되면 SSH 인증부터 점검.
3. 변경 → commit → push → Vercel 자동배포 → curl로 라이브 검증(§1).
4. 스타일·라벨·도구 분담(§5·§6·§7) 규칙을 지킬 것.
