#!/usr/bin/env bash
# 수업용 미디어 스택 올리기/내리기.
#
#   class.sh up      수업 전 — 서비스 기동 + 준비될 때까지 대기
#   class.sh warm    첫 컷 지연(콜드 약 322초)을 미리 치러 둔다
#   class.sh down    수업 후 — 전부 내려서 메모리 반환
#   class.sh status  지금 상태
#
# 기동 순서가 중요하다. dgx-media 의 health 는 h3 가 떠 있어야 200 을 준다.

set -uo pipefail

SERVICES="h3.service h3-bridge.service dgx-media.service"
MCP_DIR=/home/rgh/services/dgx-mcp
MEDIA_HEALTH=http://127.0.0.1:8092/health
MCP_HEALTH=http://127.0.0.1:8093/health

say() { printf '%s\n' "$*"; }

wait_for() {  # wait_for <url> <초>
  local url=$1 limit=$2 waited=0
  while [ "$waited" -lt "$limit" ]; do
    if curl -fsS -m 5 "$url" >/dev/null 2>&1; then return 0; fi
    sleep 10
    waited=$((waited + 10))
    printf '  … %s초\n' "$waited"
  done
  return 1
}

up() {
  say "서비스 기동 중…"
  sudo systemctl start h3.service h3-bridge.service || return 1
  sudo systemctl start dgx-media.service || return 1

  say "모델 적재를 기다린다 (보통 1~2분)"
  if wait_for "$MEDIA_HEALTH" 300; then
    say "미디어 준비 완료"
  else
    say "5분 안에 준비되지 않았다. journalctl -u dgx-media.service -n 50 을 확인할 것"
    return 1
  fi

  if ! curl -fsS -m 5 "$MCP_HEALTH" >/dev/null 2>&1; then
    say "MCP 서버 기동"
    ( cd "$MCP_DIR" && nohup .venv/bin/python mcp_server.py >> run.log 2>&1 & )
    sleep 5
  fi
  curl -fsS -m 5 "$MCP_HEALTH" >/dev/null 2>&1 && say "MCP 준비 완료" || say "MCP 기동 실패 — $MCP_DIR/run.log 확인"

  status
}

warm() {
  # H3 를 메모리에 올려둔다. 이걸 안 하면 수업 첫 컷이 5분 넘게 걸린다.
  say "워밍업 — 한 컷 뽑는다. 약 3~5분 걸린다."
  local key
  key=$(sudo -u rgh cat /home/rgh/.config/dgx-media/config.json 2>/dev/null \
        | python3 -c 'import json,sys;print(json.load(sys.stdin)["api_key"])' 2>/dev/null)
  if [ -z "${key:-}" ]; then
    say "키를 찾지 못했다. 워밍업은 건너뛴다 (수업 첫 컷이 느려질 수 있음)"
    return 0
  fi
  local boundary="----warm$$"
  {
    printf -- "--%s\r\nContent-Disposition: form-data; name=\"prompt\"\r\n\r\n따뜻한 실내, 성인 한 명의 미디엄 클로즈업. 글자 없음.\r\n" "$boundary"
    printf -- "--%s\r\nContent-Disposition: form-data; name=\"width\"\r\n\r\n512\r\n" "$boundary"
    printf -- "--%s\r\nContent-Disposition: form-data; name=\"height\"\r\n\r\n768\r\n" "$boundary"
    printf -- "--%s\r\nContent-Disposition: form-data; name=\"num_inference_steps\"\r\n\r\n10\r\n" "$boundary"
    printf -- "--%s\r\nContent-Disposition: form-data; name=\"extra_params\"\r\n\r\n{\"task\":\"t2va\",\"duration\":6,\"audio_flow_shift\":3}\r\n" "$boundary"
    printf -- "--%s--\r\n" "$boundary"
  } > /tmp/warm-body.$$
  curl -s -o /tmp/warm.mp4 -w "  응답 %{http_code} · %{size_download} 바이트 · %{time_total}초\n" \
    -H "Authorization: Bearer $key" \
    -H "Content-Type: multipart/form-data; boundary=$boundary" \
    --data-binary @/tmp/warm-body.$$ \
    --max-time 900 \
    http://127.0.0.1:4100/api/media/v1/videos/sync
  rm -f /tmp/warm-body.$$ /tmp/warm.mp4
  say "워밍업 끝. 이제 한 컷당 약 165초."
}

down() {
  say "MCP 서버 정지"
  pkill -f "$MCP_DIR/mcp_server.py" 2>/dev/null || pkill -f mcp_server.py 2>/dev/null || true
  say "미디어 서비스 정지"
  sudo systemctl stop dgx-media.service h3-bridge.service h3.service
  sleep 3
  status
}

status() {
  say ""
  say "── 서비스 ──"
  for s in $SERVICES; do printf '  %-22s %s\n' "$s" "$(systemctl is-active "$s")"; done
  printf '  %-22s %s\n' "mcp_server.py" "$(pgrep -f mcp_server.py >/dev/null && echo active || echo inactive)"
  say "── 메모리 ──"
  free -g | sed -n 2p | awk '{printf "  총 %sG · 사용 %sG · 가용 %sG\n", $2, $3, $7}'
  say "── 준비 상태 ──"
  curl -fsS -m 5 "$MEDIA_HEALTH" >/dev/null 2>&1 && say "  미디어 ready" || say "  미디어 내려감"
  curl -fsS -m 5 "$MCP_HEALTH"   >/dev/null 2>&1 && say "  MCP ready"    || say "  MCP 내려감"
}

case "${1:-status}" in
  up)     up ;;
  warm)   warm ;;
  down)   down ;;
  status) status ;;
  *)      say "사용법: class.sh {up|warm|down|status}"; exit 2 ;;
esac
