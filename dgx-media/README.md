# DGX Spark 가족용 통합 미디어

- 이미지: FLUX.2 Klein 4B, 512~1024 계열, 기본 4 steps
- 음악/효과음: Stable Audio 3 Medium TensorRT, 3~380초(디코더 실측 최소 약 2.97초)
- 영상: MiniMax H3, 권장 512x768·6초·10 steps
- 외부 접속: 기존 8443 관리 게이트웨이의 H3 키 인증 재사용
- 내부 실행: 8092 loopback 전용, 이미지·음악·영상 요청은 한 번에 하나씩 처리

클라이언트는 `tools/dgx-media.py`, 전달용 문구는 `CLAUDE_CODE_CODEX_SETUP_PROMPT.md`를 사용한다. API 키는 저장소에 두지 않는다.

이미지 환경은 시스템 CUDA PyTorch를 재사용하는 `--system-site-packages` venv이며, H3와의 의존성 충돌을 막기 위해 `requirements.txt` 버전을 독립 설치한다.

## 운영 확인

```bash
sudo systemctl status dgx-media.service
curl -fsS http://127.0.0.1:8092/health
journalctl -u dgx-media.service -n 100 --no-pager
```

모델은 `black-forest-labs/FLUX.2-klein-4B`만 허용한다. DGX 캐시에 있는 다른 이미지 체크포인트는 이 서비스에서 참조하지 않는다.
