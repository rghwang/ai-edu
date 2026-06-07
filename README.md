# 우리 교실 AI 수업 현황 페이지

빌드가 필요 없는 정적 사이트입니다. 진행 상황(예정/진행중/완료)과 주차별 메모를 클릭으로 기록하고, 브라우저에 자동 저장됩니다.

## 페이지 구성
- `index.html` — 수업 현황 대시보드(진행률·주차별 카드·메모). 사이트의 첫 화면.
- `vision.html` — 비전 & 커리큘럼(왜·무엇을). 도착점과 8주 커리큘럼 전체.
- `gemini.html` — Gemini 이미지·영상 만들기 교사 실전 가이드(단계·프롬프트·안전·수준별).
- `w1.html` — W1 상세 수업안.
- `w1-slides.html` — W1 학생용 슬라이드.

## Vercel에 배포하기 (셋 중 아무거나)

### 방법 1 — 드래그 앤 드롭 (가장 쉬움, 1분)
1. https://vercel.com 가입/로그인 (GitHub·Google 계정으로 가능)
2. https://vercel.com/new 접속
3. 이 폴더(`index.html`이 든 폴더)를 화면에 그대로 끌어다 놓기
4. **Deploy** 클릭 → 끝. `https://프로젝트이름.vercel.app` 주소가 생깁니다.

### 방법 2 — GitHub 연동 (수정·재배포 자동화)
1. 이 파일들을 GitHub 저장소에 올리기
2. Vercel에서 **New Project → Import**로 그 저장소 선택
3. 설정은 전부 기본값(Framework: Other) → **Deploy**
4. 이후 GitHub에 push하면 자동으로 다시 배포됩니다.

### 방법 3 — CLI
```bash
npm i -g vercel
cd 이폴더
vercel        # 안내에 따라 로그인 후 배포
vercel --prod # 정식(프로덕션) 배포
```

## 참고
- 진행 상황·메모는 **연 브라우저에 저장**됩니다(기기마다 따로). 여러 기기에서 같은 데이터를 보려면 별도 백엔드가 필요해요.
- 수업이 늘어나거나 내용을 바꾸고 싶으면 `index.html` 안의 `past` / `phase1` / `phase2` 데이터 배열만 수정하면 됩니다.
