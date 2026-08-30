# Claude Code / Codex에 그대로 전달할 설치 문구

상세 설명은 `https://rg-teach-ai.vercel.app/dgx-media/CLAUDE_CODE_GUIDE.md`에서 확인한다.

아래 블록만 복사해 Claude Code 또는 Codex에 붙여 넣는다. API 키는 채팅에 붙여 넣지 말고, 설치 도중 터미널의 숨김 입력 칸에 직접 넣는다.

```text
이 컴퓨터에서 우리 가족용 DGX Spark 이미지·음악·영상 생성기를 쓰게 설정해줘.

1. https://rg-teach-ai.vercel.app/tools/dgx-media.py 를 ~/.local/bin/dgx-media 로 다운로드해.
2. 실행 권한을 주고, ~/.local/bin 이 PATH에 없으면 현재 셸 설정에 추가해.
3. `dgx-media setup`을 실행해. API 키 입력은 내가 터미널에서 직접 하게 멈춰 줘. 키를 채팅, 로그, 코드, git 저장소에 쓰지 마.
4. `dgx-media status`로 image/audio/video 세 항목이 준비됐는지 확인해.
5. 현재 프로젝트에 `generated-media/` 폴더를 만들고 `.gitignore`에는 필요에 따라 대용량 wav/mp4만 제외해.
6. 테스트 이미지를 한 장 만들어 `generated-media/dgx-test.png`에 저장해. 프롬프트는 “따뜻한 종이 질감의 가족 친화적인 아케이드 게임 배경, 글자 없음, 16비트 픽셀 아트”로 해.
7. 성공하면 이 프로젝트에서 쓸 명령 예시 세 개를 짧게 알려줘. 실패하면 키 값을 출력하지 말고 HTTP 상태와 원인만 진단해.

이후 내가 이미지·배경음악·효과음·H3 영상을 요청하면 먼저 dgx-media 명령을 사용하고 결과 파일을 프로젝트에 연결해. 이미지 기본값은 1024x1024/4 steps, 음악은 30초/8 steps, H3 영상은 512x768/6초/10 steps로 해. H3 대사 영상은 한 화면 한 화자·한 문장 원칙을 지켜.
```

이미 설치된 컴퓨터라면 더 짧게 다음 문구만 전달한다.

```text
이 프로젝트의 생성 자산은 `dgx-media` 명령을 사용해 만들어줘. 먼저 `dgx-media status`를 확인하고, image/audio/video 중 알맞은 하위 명령으로 생성한 뒤 결과 파일을 프로젝트에 적용해. API 키나 ~/.config/dgx-media/config.json 내용은 절대 출력하거나 git에 넣지 마.
```
