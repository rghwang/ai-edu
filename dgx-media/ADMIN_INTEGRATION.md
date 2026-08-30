# 기존 8443 관리 게이트웨이 통합

DGX의 `/home/rgh/litellm-admin/app.py`에는 다음 변경이 적용되어 있다.

- 내부 미디어 주소: `MEDIA_UPSTREAM_URL` 환경변수, 기본값은 loopback의 8092 서비스
- 외부 경로: `/api/media/{path:path}`
- 인증: 기존 `h3_keys` 테이블과 RPM 제한 재사용
- 프록시 제한시간: 생성 작업을 위해 1시간
- 통과 응답 헤더: content type/disposition, cache control, DGX job ID
- `build_guide_md()`에 FLUX.2·Stable Audio 3·MiniMax H3 통합 경로와 설치 문서 링크 추가

변경 전 파일은 DGX의 `/home/rgh/litellm-admin/app.py.bak-before-media-20260830`에 보관했다. 현재 전용 키 이름은 `family-media`이며 실제 키 값은 저장소에 없다. 새 키 발급·회전은 기존 8443 관리자 화면의 H3 키 관리 기능을 사용한다.
