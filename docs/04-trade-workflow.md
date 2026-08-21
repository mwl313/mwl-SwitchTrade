# MWL-SwitchTrade — 트레이드 워크플로우 v1 (2026-08-21 검증 완료)

> 최초 실측 성공: 2026-08-21, 뮤/세레비/지라치 ↔ 꼬렛 3마리 (3회 트레이드 전부 성공)
> 목적: "운 좋게 한 번 된 것"이 아니라 **반복 가능한 절차**로 고정한다.

---

## 1. 오늘의 프로그레스 (2026-08-21)

### 달성
| 항목 | 결과 |
|---|---|
| 스캔 (스위치 발견) | ✅ `found 1, comm_id=0x01006fa0233f8000, ch1/ch6, 2.4GHz, accept=0` |
| assoc (LDN 조인) | ✅ `ldnclient: associated` — **status 1 해결 확정** |
| 트레이드 3회 | ✅ 전부 성공 (received_trade_trade1~3_RATTATA.pk3) |
| 수신 검증 | ✅ .pk3 3개 생성 + 로컬 백업 (`~/Projects/MWL-SwitchTrade/received-20260821/`) |
| 스위치 수신 | ✅ 뮤/세레비/지라치 3마리 도착 확인 (주인님 확인) |

### 프로젝트 진행도 갱신
```
Phase 0 (환경 준비) → 100% ✅
Phase 1 (PoC 재현)  → 100% ✅  (마일스톤 M0 달성)
Phase 2 (PC↔PC 인터넷 브리지) → 0% — 다음 목표
```

---

## 2. 발생한 문제와 해결책 (영구성 평가)

| # | 문제 | 원인 | 해결책 | 1회성? | 영구 적용 위치 |
|---|---|---|---|---|---|
| 1 | assoc status code 1 (스위치가 조인 거부) | **stale vif 누수** — 실패한 조인이 `ldnclient` vif를 남기면 다음 assoc이 status 1로 거부 (원작자 코드 주석으로 확정) | **free_radio 하이브리드 패치**: free_radio 호출 유지(join 전 LDN vif 정리) + else 브랜치의 `nmcli managed no`/`down` 제거 | ❌ 영구 | `frlgsim/transport.py` (MWL 주석 1건, 159-162행) |
| 2 | 스캔/조인 중 EBUSY | NetworkManager가 wlx를 관리 → ldn이 채널 변경 불가 | **NM unmanaged 설정**: `/etc/NetworkManager/conf.d/unmanaged-wlx.conf`에 wlx MAC 등록 | ❌ 영구 | `/etc/NetworkManager/conf.d/` (재부팅 유지) |
| 3 | 카드 수신 사망 (수신 0) | ① Windows USB 선택적 절전 (30분~1시간 주기, VMware 패스스루) ② rtl8xxxu IQK 실패 버그 | **usbreset이 유일한 즉시 복구**: `sudo usbreset 0bda:8179` → 3초 후 인터페이스 재설정. Windows powercfg로 절전 차단(주인님 실행) | ❌ 명령이지만 절차로 고정 | run_trade.sh v5에 통합 + 아래 대응 절차 참조 |
| 4 | 드라이버 재로드가 카드를 죽임 | `modprobe -r rtl8xxxu` 재로드가 수신 사망 유발 (2회 실측) | **래퍼에서 usbreset으로 대체** (modprobe 재로드 금지) | ❌ 영구 | `run_trade.sh` v5 |
| 5 | ldn.scan hang → VM 전체 먹통 (4회) | **rtl8188eus 커스텀 드라이버** + ldn.scan 조합 (커널 레벨 blocking, trio 타임아웃 무력) | **rtl8188eus 폐기 + 커널 7.0 + rtl8xxxu 복귀** (스냅샷 복원) | ❌ 영구 (드라이버 고정) | 커널 7.0 + rtl8xxxu 고정 |
| 6 | NM reload로 VM 네트워크 전체 사망 | unmanaged 설정을 reload로 즉시 적용 시도 | **적용은 재부팅으로만** — reload 절대 금지 | ❌ 교훈으로 고정 | 운영 규칙 |
| 7 | `trio.with_timeout` 미지원 | trio 0.33에서 API 변경 | `trio.fail_after(30)` 사용 | ❌ 영구 | `scan_phy.py` |

**결론: 해결책 전부 코드/설정 파일로 영구 저장됨. 1회성은 없음.** 단, 카드 수신 사망(3번)은 하드웨어/호스트 특성상 **재발 가능**하므로 절차로 대응한다 (아래 4-1 참조).

---

## 3. 표준 트레이드 절차 (반복 가능한 워크플로우)

### 사전 준비 (최초 1회)
1. VM 부팅 (Windows VMware) — 커널 7.0 + rtl8xxxu 자동 로드 확인
2. SSH 접속: `ssh -i ~/.ssh/aria_bridge aria@100.109.113.113`
3. 확인: `lsmod | grep rtl8xxxu`, `nmcli -t -f DEVICE,STATE device | grep wlx` → **unmanaged** 표시
4. 몬 파일 확인: `ls ~/mons/*.pk3` (보낼 포켓몬 .pk3)
5. **스위치: NSO GB 앱 → FRLG → 디렉트 코너 → 트레이드 → Leader** ("POKEMON TRADES! Awaiting..." 화면 유지)

### 트레이드 실행 (매회)
```bash
# 1. 스캔으로 스위치 확인 (phy 번호는 매번 다름 — 자동 감지)
PHY=$(ssh -i ~/.ssh/aria_bridge aria@100.109.113.113 "iw phy | grep Wiphy | head -1 | awk '{print \$2}'")
ssh -i ~/.ssh/aria_bridge aria@100.109.113.113 "sudo ip link set wlx00ada7117309 down; sudo iw dev wlx00ada7117309 set type monitor; sudo ip link set wlx00ada7117309 up; sudo iw dev wlx00ada7117309 set channel 1; sudo /home/aria/ldnvenv/bin/python /home/aria/scan_phy.py $PHY"
# → found 1 이면 진행. found 0이면 아래 4번 절차.

# 2. 트레이드 실행 (래퍼가 usbreset + phy 감지 + monitor 보장)
ssh -i ~/.ssh/aria_bridge aria@100.109.113.113 \
  "sudo bash ~/frlg-ldn-trade/run_trade.sh --live --verbose \
   --keys /root/.switch/prod.keys --trades 3 --slots 0,1,2 \
   -o /home/aria/mons/received_trade.pk3 /home/aria/mons/*.pk3"

# 3. 스위치 조작 (수동 — 순정 원칙)
#    ① 트레이드 화면에서 "EMU" 참가 확인/승인
#    ② 캐릭터를 왼쪽 의자로 이동 → 앉기
#    ③ 보낼 포켓몬 선택 → 확인 (트레이드 횟수만큼 반복)

# 4. 완료 확인
ssh -i ~/.ssh/aria_bridge aria@100.109.113.113 "ls -la ~/mons/received_trade_trade*.pk3"

# 5. 프로세스 정리 (완료 후에도 대기 상태로 남음)
ssh -i ~/.ssh/aria_bridge aria@100.109.113.113 "sudo pkill -INT -f frlgtrade.py"

# 6. 수신 파일 로컬 백업
scp -i ~/.ssh/aria_bridge "aria@100.109.113.113:~/mons/received_trade_trade*.pk3" ~/Projects/MWL-SwitchTrade/received-<날짜>/
```

### 핵심 옵션 설명
| 옵션 | 의미 |
|---|---|
| `--trades 3` | 3회 트레이드 |
| `--slots 0,1,2` | 우리 파티 슬롯 0,1,2에 있는 .pk3 (뮤/세레비/지라치)를 순서대로 송신 |
| `.pk3` 파일들 | PC 측 "파티" — frlgsim이 자동으로 선택·교환 (버튼 조작 불필요) |

---

## 4. 실패 시나리오 대응 (재발 시 절차)

### 4-1. 카드 수신 사망 (스캔 0 + tcpdump 0) — 가장 흔한 케이스
```bash
# ① usbreset으로 즉시 복구 (재부팅 불필요)
ssh ... "sudo usbreset 0bda:8179; sleep 3"
# ② 인터페이스 재설정 후 스캔
ssh ... "sudo ip link set wlx00ada7117309 down; sudo iw dev wlx00ada7117309 set type monitor; sudo ip link set wlx00ada7117309 up; sudo iw dev wlx00ada7117309 set channel 1"
# ③ 그래도 0이면: Windows에서 pnputil /restart-device "USB\VID_0BDA&PID_8179" (재부팅 없이)
# ④ 최후: Windows 재시작 (100% 복구 — 8/20 실측)
# ⑤ 예방: Windows powercfg로 USB 선택적 절전 차단 (1회성 설정, 영구)
```

### 4-2. 스캔 found 0 (카드는 살아있음)
- 스위치가 5GHz로 광고 중일 가능성 (RTL8188EU는 2.4GHz 전용) → **스위치에서 NSO GB 앱 완전 재시작 → 리더 재진입** (2.4GHz 복귀 시도)
- 스위치 화면 꺼짐/슬립 → 화면 켜고 리더 상태 유지

### 4-3. assoc 실패 (join 재시도 3회 후 RuntimeError)
- 원작자 코드가 자동 재시도 3회 + free_radio vif 정리 수행 (이미 적용됨)
- 그래도 실패: `iw dev`로 `ldnclient`/`ldn` vif 잔존 확인 → `sudo iw dev ldnclient del` 등 수동 정리 후 재시도

### 4-4. EBUSY (Device or resource busy)
- NM이 wlx를 다시 관리하기 시작한 경우 → `/etc/NetworkManager/conf.d/unmanaged-wlx.conf` 확인 + 재부팅
- wlx를 down 상태로 두고 스캔 (EBUSY 회피, 검증됨)

---

## 5. 재현성 보장 체크리스트 (트레이드 전 매번)

- [ ] 커널 7.0.0-30-generic + rtl8xxxu 로드 (`lsmod`)
- [ ] wlx unmanaged (`nmcli device` → wlx:unmanaged)
- [ ] transport.py에 MWL 주석 1건 (하이브리드 패치) — `grep -c MWL frlgsim/transport.py` = 1
- [ ] run_trade.sh v5 (usbreset 방식) — `grep usbreset run_trade.sh`
- [ ] scan_phy.py 존재 (`/home/aria/scan_phy.py`, fail_after 30s)
- [ ] 스위치 리더 상태 + 화면 유지
- [ ] 스캔 found 1 확인 후 트레이드 시작

## 6. 알려진 잔여 리스크

| 리스크 | 영향 | 대응 |
|---|---|---|
| USB 절전 재발 (30분~1시간 주기) | 카드 수신 사망 | usbreset 즉시 복구 (4-1) — 절대적 해결은 Windows 설정 유지 |
| 스위치 5GHz 광고 | 스캔 불가 | 앱 재시작으로 2.4GHz 복귀 (8/20 첫 성공은 ch11) |
| 스위치 슬립 | 광고 중단 | 화면 유지, 리더 재진입 |
| 트레이드 중간 끊김 | 부분 수신 | `received_trade_trade{N}` 파일로 단계 확인, 재시도 |
| ldn.scan hang | — | rtl8188eus 사용 금지로 원천 차단됨 (rtl8xxxu에선 미발생) |

---

*작성: 2026-08-21 | 검증: 최초 트레이드 3회 성공 실측 기준 | 다음 갱신: 2회차 트레이드 성공 시*
