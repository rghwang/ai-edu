# DGX Spark 가족용 통합 미디어

- 이미지: FLUX.2 Klein 4B, 512~1024 계열, 기본 4 steps
- 음악/효과음: Stable Audio 3 Medium TensorRT, 3~380초(디코더 실측 최소 약 2.97초)
- 영상: MiniMax H3, 권장 512x768·6초·10 steps
- 외부 접속: 기존 8443 관리 게이트웨이의 H3 키 인증 재사용
- 내부 실행: 8092 loopback 전용, 가용 통합 메모리에 따른 모델 간 병렬 처리

클라이언트는 `tools/dgx-media.py`, Claude Code 상세 가이드는 `CLAUDE_CODE_GUIDE.md`, 짧은 전달용 문구는 `CLAUDE_CODE_CODEX_SETUP_PROMPT.md`를 사용한다. API 키는 저장소에 두지 않는다.

이미지 환경은 시스템 CUDA PyTorch를 재사용하는 `--system-site-packages` venv이며, H3와의 의존성 충돌을 막기 위해 `requirements.txt` 버전을 독립 설치한다.

## 병렬 처리 정책

단일 GB10의 128GB 통합 메모리에서 시스템용 12GiB를 남기고, 실측 부하 테스트를 거친 동시 작업 예약 한도를 44GiB로 둔다. 새 작업은 예약 한도와 실제 `MemAvailable`을 모두 통과해야 시작한다.

| 작업 | 작업당 예약 | 같은 모델 동시 실행 |
|---|---:|---:|
| FLUX 이미지 | 예열 14GiB / 최초 로딩 30GiB | 1 |
| Stable Audio | 8GiB | 최대 4 |
| MiniMax H3 | 22GiB | 1 |

전체 동시 실행은 최대 4개다. 따라서 예열된 이미지+H3+사운드 1개(44GiB), 이미지+사운드 3개(38GiB), H3+사운드 2개(38GiB), 사운드 4개(32GiB)까지 예약상 허용한다. 실제 가용 메모리가 12GiB 아래로 내려갈 조합은 자동 대기한다. H3 자체의 한 번에 한 영상 제한과 FLUX 파이프라인의 한 번에 한 이미지 제한은 유지한다.

`GET /v1/queue` 또는 `dgx-media status`에서 모델별 실행·대기 수, 가용 메모리, 예약량을 확인할 수 있다. 생성 결과에는 `queue_wait_seconds`가 포함된다.

## 운영 확인

```bash
sudo systemctl status dgx-media.service
curl -fsS http://127.0.0.1:8092/health
curl -fsS http://127.0.0.1:8092/v1/queue
journalctl -u dgx-media.service -n 100 --no-pager
```

모델은 `black-forest-labs/FLUX.2-klein-4B`만 허용한다. DGX 캐시에 있는 다른 이미지 체크포인트는 이 서비스에서 참조하지 않는다.
