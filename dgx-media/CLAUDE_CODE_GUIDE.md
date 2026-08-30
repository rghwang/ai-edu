# Claude Code에서 DGX 이미지·사운드·영상 사용하기

이 가이드는 Claude Code가 프로젝트 작업 중 DGX Spark의 로컬 생성 모델을 호출해 이미지, 배경음악·효과음, MiniMax H3 영상을 만들고 결과 파일을 프로젝트에 적용하는 방법을 설명한다.

## 1. 지원 기능

| 명령 | 모델 | 기본 용도 |
|---|---|---|
| `dgx-media image` | FLUX.2 Klein 4B | 게임 배경, 아이템, 캐릭터, UI 장식 |
| `dgx-media audio` | Stable Audio 3 Medium | 배경음악, 효과음, 징글 |
| `dgx-media video` | MiniMax H3 | 한국어 대사가 포함된 세로 드라마 영상 |

DGX는 가용 통합 메모리를 확인해 서로 다른 작업을 병렬 처리한다. 전체 최대 4작업, 이미지 1개, H3 영상 1개, 사운드 4개까지 동시에 실행할 수 있다. 메모리가 부족한 조합은 실패시키지 않고 자동으로 대기시킨다.

## 2. 컴퓨터당 한 번만 설치

Claude Code에 아래 작업을 요청하거나 터미널에서 직접 실행한다.

```bash
mkdir -p ~/.local/bin
curl -fsSL https://rg-teach-ai.vercel.app/tools/dgx-media.py \
  -o ~/.local/bin/dgx-media
chmod 755 ~/.local/bin/dgx-media
```

`~/.local/bin`이 PATH에 없다면 사용하는 셸 설정에 추가한다. macOS 기본 zsh 예시는 다음과 같다.

```bash
export PATH="$HOME/.local/bin:$PATH"
```

API 키는 채팅에 붙여 넣지 않고 터미널의 숨김 입력으로 저장한다.

```bash
dgx-media setup
```

키는 `~/.config/dgx-media/config.json`에 권한 600으로 저장된다. 이 파일의 내용은 화면에 출력하거나 Git에 추가하면 안 된다.

설치 확인:

```bash
dgx-media status
```

정상이면 최상단에 `"status": "ready"`가 나오고 image, audio, video가 준비 상태로 표시된다.

## 3. 프로젝트에서 사용하는 기본 흐름

Claude Code는 생성 전에 상태를 확인하고 결과 전용 폴더를 만든다.

```bash
dgx-media status
mkdir -p generated-media
```

권장 흐름:

1. 현재 프로젝트의 화면 크기, 화풍, 파일 형식을 먼저 확인한다.
2. 필요한 자산만 목록으로 정리한다.
3. 빠른 저해상도·낮은 스텝으로 한 장 또는 한 트랙을 시험한다.
4. 결과를 확인한 후 필요한 최종본만 생성한다.
5. 생성 파일을 프로젝트 코드에 연결하고 실제 실행 화면에서 검증한다.
6. 사용하지 않는 후보는 프로젝트에 무분별하게 추가하지 않는다.

## 4. 이미지 생성

기본 예시:

```bash
dgx-media image \
  "가족 친화적인 16비트 픽셀 아트 숲속 성 배경, 횡스크롤 게임, 글자와 로고 없음" \
  --size 1024x576 \
  --steps 4 \
  --seed 1201 \
  -o generated-media/forest-castle-bg.png
```

자주 쓰는 크기:

- 정사각형 아이템·아이콘: `512x512`, `1024x1024`
- 가로 게임 배경: `1024x576`
- 세로 배경·포스터: `576x1024`

가로·세로는 64의 배수여야 하며 전체 면적은 1,048,576픽셀 이하여야 한다. 기본 4스텝을 권장하고, 초안은 1~2스텝으로 시험할 수 있다. 같은 seed를 사용하면 수정 전후를 비교하기 쉽다.

최초 호출은 모델 로딩 때문에 약 4분 걸릴 수 있다. 예열 후 512px·4스텝 실측은 약 1분 48초였다.

## 5. 음악과 효과음 생성

30초 배경음악:

```bash
dgx-media audio \
  "밝은 16비트 아케이드 모험 배경음악, 자연스럽게 반복되는 끝부분, 보컬 없음" \
  --seconds 30 \
  --steps 8 \
  --seed 2201 \
  -o generated-media/adventure-bgm.wav
```

짧은 효과음:

```bash
dgx-media audio \
  "짧고 밝은 동전 획득 아케이드 효과음, 보컬 없음" \
  --seconds 3 \
  --steps 8 \
  --seed 2202 \
  -o generated-media/coin.wav
```

지원 길이는 3~380초다. TensorRT 디코더의 실제 최소 길이가 약 2.97초이므로 3초 미만은 사용할 수 없다. 사운드는 최대 4개까지 동시에 실행 가능하다.

## 6. MiniMax H3 영상 생성

권장 기술 기본값은 세로 512×768, 6초, 10스텝이다.

```bash
dgx-media video \
  "세로형 한국 웹드라마. 따뜻한 교실, 성인 한국인 여성 한 명의 미디엄 클로즈업. 다른 사람은 보이지 않는다. 화면 옆 상대를 보며 한국어로 정확히 한 문장만 말한다: ‘찾았어, 이제 시작하자.’ 자연스러운 입 모양과 절제된 표정, 화면 글자·로고 없음." \
  --width 512 \
  --height 768 \
  --seconds 6 \
  --steps 10 \
  --seed 3201 \
  -o generated-media/scene-01.mp4
```

참조 이미지로 첫 프레임의 인물·장소를 지정할 수도 있다.

```bash
dgx-media video \
  "참조 이미지와 같은 성인 인물과 의상. 한 명만 보이며 한국어 한 문장만 말한다: ‘문이 열렸어.’" \
  --reference generated-media/character-reference.png \
  --width 512 --height 768 --seconds 6 --steps 10 \
  -o generated-media/scene-02.mp4
```

H3 대사 영상 규칙:

- 한 화면에 화자 한 명
- 한 테이크에 짧은 문장 하나
- 의도한 한국어 대사가 실제 음성에 정확히 들어갔는지 확인
- 입 모양, 얼굴·의상·장소 연속성 확인
- 잘못된 대사를 자막으로 덮지 말고 해당 테이크만 다시 생성
- H3 자체 음성을 유지하고 별도 TTS로 교체하지 않기

H3는 모델 특성상 영상 한 개씩 처리한다. 여러 요청은 순서대로 대기한다.

## 7. 병렬 처리와 대기 확인

현재 메모리 정책:

- 전체 최대 4작업
- 시스템용 최소 가용 메모리 12GiB 유지
- 동시 작업 예약 한도 44GiB
- 예열 이미지 14GiB, 최초 이미지 30GiB, 사운드 8GiB, H3 22GiB로 계산

허용 예시:

- 사운드 4개
- 예열 이미지 1개 + 사운드 3개
- H3 1개 + 사운드 2개
- 예열 이미지 1개 + H3 1개 + 사운드 1개

상태 확인:

```bash
dgx-media status
```

주요 항목:

- `active_jobs`: 현재 실행 중인 전체 작업 수
- `waiting_jobs`: 메모리 또는 모델 제한 때문에 기다리는 작업 수
- `active_by_type`, `waiting_by_type`: 매체별 실행·대기 수
- `available_gib`: 현재 실제 가용 메모리
- `active_reserved_gib`: 실행 중 작업의 예약 메모리
- `queue_wait_seconds`: 각 생성 명령이 실제 시작 전 기다린 시간

대기 중인 명령을 다시 실행하면 중복 생성될 수 있다. 오류가 나오지 않았다면 기존 터미널을 그대로 기다린다.

## 8. 결과 검증

```bash
file generated-media/forest-castle-bg.png
file generated-media/adventure-bgm.wav
ffprobe -v error \
  -show_entries format=duration:stream=codec_name,width,height,sample_rate \
  -of default=noprint_wrappers=1 \
  generated-media/scene-01.mp4
```

Claude Code는 파일이 만들어졌다는 사실만 확인하지 말고 다음도 검증해야 한다.

- 이미지가 프로젝트가 요구하는 크기·화풍·투명도에 맞는지
- WAV가 무음이 아니며 의도한 길이인지
- MP4에 H.264 영상과 AAC 음성이 모두 있는지
- 게임·웹페이지에서 경로와 대소문자가 정확한지
- 모바일 화면과 배포본에서도 파일이 정상 로드되는지

## 9. 오류 대응

| 증상 | 대응 |
|---|---|
| `401` | `dgx-media setup`을 다시 실행하거나 관리자에게 키 상태 확인 |
| `429` | 분당 호출 제한이므로 잠시 기다린 후 재시도 |
| 명령이 오래 멈춘 것처럼 보임 | 다른 작업 실행 여부를 `dgx-media status`로 확인 |
| `width/height` 오류 | 64의 배수와 최대 픽셀 수 확인 |
| 사운드 길이 오류 | 3~380초로 설정 |
| `500` | 키를 출력하지 말고 오류 본문과 작업 종류만 관리자에게 전달 |

키, `~/.config/dgx-media/config.json`, 관리자 비밀번호는 로그·문서·Git·Claude 대화에 넣지 않는다.

## 10. Claude Code에 전달할 문구

설치부터 필요한 컴퓨터:

```text
이 컴퓨터에서 DGX Spark 이미지·사운드·H3 영상 생성기를 사용하게 설정해줘. 먼저 https://rg-teach-ai.vercel.app/dgx-media/CLAUDE_CODE_GUIDE.md 를 읽고 그 절차를 따라줘. API 키 입력 단계에서는 내가 터미널에 직접 입력할 수 있게 멈추고, 키나 ~/.config/dgx-media/config.json 내용을 채팅·로그·Git에 절대 출력하지 마. 설치 후 dgx-media status를 확인하고 generated-media/dgx-test.png 테스트 이미지 한 장을 만든 뒤 결과를 알려줘.
```

이미 설치된 컴퓨터:

```text
이 프로젝트의 생성 자산은 dgx-media를 사용해 만들어줘. 먼저 dgx-media status로 실행·대기·가용 메모리를 확인해. 필요한 이미지·음악·H3 영상만 generated-media/에 생성하고 프로젝트에 연결한 뒤 실제 실행 결과를 검증해. 대기 중인 명령을 중복 실행하지 말고 API 키나 설정 파일 내용은 절대 출력하지 마. H3 영상은 한 화면 한 화자·한 문장과 네이티브 대사 검사를 지켜.
```

## 11. iPad에서 사용하는 방법

### 권장: Mac의 Claude Code를 iPad에서 조종하기

Mac에서 이미 `dgx-media setup`을 마쳤다면, iPad에서 GitHub 원격 세션을 새로 만들지 말고 **Remote Control**을 사용한다. 코드는 Mac에서 실행되고 iPad는 그 세션을 조종하므로 Mac에 저장된 DGX 키와 `dgx-media` 명령을 그대로 쓸 수 있다.

Mac의 프로젝트 터미널에서 실행한다.

```bash
cd /Users/사용자이름/프로젝트-폴더
claude remote-control --name "DGX 미디어 작업"
```

처음이면 `claude`를 실행한 뒤 `/login`으로 Claude 계정에 로그인하고, 프로젝트 신뢰 확인을 한 번 완료한다. 터미널에 표시되는 세션 URL 또는 QR 코드를 iPad에서 열거나, iPad의 `claude.ai/code`에서 같은 Claude 계정으로 로그인한 뒤 컴퓨터 아이콘이 있는 `DGX 미디어 작업` 세션을 선택한다.

이 방식의 조건은 Mac이 켜져 있고 네트워크에 연결되어 있으며 `claude remote-control` 프로세스가 계속 실행 중인 것이다. iPad에서 명령을 보내도 실제 파일·키·DGX 접속은 Mac에서 처리된다.

### 차선: GitHub 원격(Claude Code on the web) 환경

GitHub 원격 세션은 Anthropic 클라우드의 새 VM에서 실행된다. Mac의 `~/.config/dgx-media/config.json`과 `~/.local/bin/dgx-media`는 보이지 않으므로, iPad Safari 문제가 아니라 실행 위치가 다른 것이 원인이다.

이 방식을 꼭 써야 한다면 Claude Code 웹 환경 설정에서 다음을 직접 구성해야 한다.

1. 네트워크 접근이 DGX 주소 `aitopatom-27f6.taildae05f.ts.net:8443`을 허용하도록 설정한다. 기본 Trusted 환경은 임의의 외부 주소를 차단할 수 있다.
2. 환경 변수에 아래 두 값을 넣는다. 값은 따옴표 없이 입력한다.

   ```text
   DGX_MEDIA_BASE_URL=https://aitopatom-27f6.taildae05f.ts.net:8443/api/media
   DGX_MEDIA_API_KEY=발급받은-family-media-키
   ```

3. 환경의 setup script에 다음을 넣어 클라이언트를 설치한다.

   ```bash
   mkdir -p "$HOME/.local/bin"
   curl -fsSL https://rg-teach-ai.vercel.app/tools/dgx-media.py -o "$HOME/.local/bin/dgx-media"
   chmod 755 "$HOME/.local/bin/dgx-media"
   ```

4. 새 원격 세션을 시작한 뒤 `export PATH="$HOME/.local/bin:$PATH"`와 `dgx-media status`를 실행해 확인한다.

Claude Code 웹 환경에는 전용 비밀 저장소가 아직 없고, 환경 변수는 해당 환경을 편집할 수 있는 사람이 볼 수 있다. 따라서 학생 공용 GitHub 원격 환경에는 가족 공용 키를 넣지 않는 편이 안전하다. GitHub 저장소·`.env` 파일·프롬프트·채팅에 키를 저장하거나 붙여 넣지 않는다.
