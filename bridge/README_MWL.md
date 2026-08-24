# frlg-ldn-trade (MWL 포크) — MWL-SwitchTrade 동작 코드 본체

> 원작: tornadus/frlg-ldn-trade (AGPL-3.0) | MWL 확장: mwl313, 2026-08~

## 이 리포의 역할 (2026-08-22 방향 전환)

| 트랙 | 경로 | 상태 |
|---|---|---|
| **framerelay (트랙 B)** ⭐ | `framerelay/` + `common/mwlb.py` | **프로덕션 메인** — 투명 중계, 활성 개발 |
| EMU (트랙 A) | `frlgtrade.py` + `frlgsim/` | 🔒 **동결·보존** — 폴백·회귀 테스트용, 신규 개발 금지 |

프로젝트 전체(문서·릴레이 서버·WSL2 배포 인프라)는 **mwl313/mwl-SwitchTrade** 참조.

## 📄 다음 개발자 필독
**[HANDOFF.md](HANDOFF.md)** — 반영된 기능 대장, 검증 매트릭스, STEP 5~13 잔여 작업 끝까지, 절대 규칙.

## framerelay 빠른 시작
```bash
sudo .venv/bin/python -m framerelay \
    --iface wlx00ada7117309 \
    --host-mac <로컬_스위치_MAC> \
    --relay-url http://<릴레이>:8788 --session-id <6자리> \
    --role host|guest --verbose
```

## 원작 아카이브 (아래는 tornadus 원문)
