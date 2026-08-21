# 09 — 테스팅 Audit (2026-08-21): 연결 테스트 이슈 종합

> 작성: 2026-08-21 | 목적: 반복되는 연결 실패의 공통 원인을 정리하고 테스팅 프로세스 개선안 도출
> 상태: Audit만 (코드 변경/추가 테스트 없음 — 주인님 지시)

---

## 1. 핵심 진단: "이전 테스트의 잔재가 다음 테스트를 막는다"

오늘 모든 연결 실패는 **드라이버/커널/데몬의 상태 잔재**가 다음 실행을 오염시키는 패턴이었음.
카드나 스위치의 근본 문제가 아니라, **테스트 사이의 정리 절차가 부족**한 것이 진짜 원인.

---

## 2. 이슈 인벤토리 (실측 기준)

### I-1. stale vif 누수 (가장 빈번 · 최악)
| 항목 | 내용 |
|---|---|
| 현상 | 이전 실행이 남긴 vif(ldnclient, ldn-mon, ldn, wlx)가 phy 점유 → **EBUSY(set_channel) / Match already configured / assoc status 1** |
| 원인 | ① pkill로 프로세스 종료 시 finally 정리(free_radio) 미실행 ② 크래시(No such device 등)로 vif 잔류 ③ **free_radio가 udev rename된 vif(wlx<MAC>)를 못 지움** (LDN_VIFS 이름 기준이라) |
| 현재 대응 | 수동 `iw dev <name> del` (실측으로 확인하면서 반복) |
| 개선 | 실행 전 "phy 완전 정리" 스크립트: rename 포함 모든 vif 삭제. free_radio 패치(이름 무관 phy 소속 vif 정리) |

### I-2. udev rename (ldnclient → wlx<MAC>)
| 항목 | 내용 |
|---|---|
| 현상 | ldn이 만든 ldnclient vif가 systemd-udev에 의해 즉시 wlxa047d7b02b39로 rename → **소켓 바인딩 `No such device` (Errno 19)** |
| 원인 | Ubuntu udev 네이밍 규칙(USB 무선 = wlx<MAC>) |
| 현재 대응 | ✅ transport.py 패치 (join 후 실제 iface 감지 — 13줄, 미커밋) — 실측 검증 완료 |
| 개선 | udev 규칙 비활성화(net.ifnames=0)로 근본 해결 가능하나, 패치가 동작하므로 유지해도 무방. free_radio 정리와 연계 필요 |

### I-3. NetworkManager 개입 (오늘 최대 발견)
| 항목 | 내용 |
|---|---|
| 현상 | **REGISTER_FRAME "Match already configured" 반복 (15+회)** — 재시도로 안 풀림 |
| 원인 | unmanaged-wlx.conf가 **8188EU MAC(00:ad:a7:11:73:09)만** 지정. 카드가 8192EU(a0:47:d7:b0:2b:39)로 바뀌자 NM이 무선 인터페이스를 관리 → ldn의 프레임 등록과 충돌 |
| 현재 대응 | ✅ conf에 두 MAC 추가 + **NetworkManager 중지** (ens33은 unmanaged라 SSH 유지 확인) — 실측 검증 완료 |
| 개선 | conf를 **MAC 기반이 아닌 interface-name 기준(wlx\*)** 으로 → 카드 교체/추가에도 면역. 또는 "NM 중지"를 표준 절차로 문서화 |

### I-4. 카드 수신 사망 (silently failing)
| 항목 | 내용 |
|---|---|
| 현상 | 8188EU가 리셋 후 몇 분 내 수신 사망 (rx_packets=0, **dmesg 에러 없음**) → saw 0 / assoc 무반응 |
| 원인 | rtl8xxxu 드라이버/카드 조합의 알려진 불안정 (8192EU는 안정 — 오늘 실측) |
| 현재 대응 | authorized 토글 리셋 (usbreset/pnputil이 더 확실 — 이전 세션 실측) |
| 개선 | 테스트 전 "카드 생존 체크"(비콘 tcpdump 3초)를 표준 절차로. 죽어있으면 자동 리셋 |

### I-5. phy 번호 증가 (리셋/재부팅마다)
| 항목 | 내용 |
|---|---|
| 현상 | phy0 → phy1 → phy2... 리셋/재부팅마다 증가 → `--phy` 매번 수동 확인 |
| 현재 대응 | 매 실행 전 `iw phy` 확인 |
| 개선 | **phy 자동 감지** (rtl8xxxu wiphy를 USB ID로 찾기) — 래퍼에 포함 |

### I-6. USB 버스/디바이스 경로 변경 (재부팅 후)
| 항목 | 내용 |
|---|---|
| 현상 | 재부팅 후 authorized 토글 경로가 2-2 → 3-2로 변경 (VMware가 다른 버스에 연결) |
| 현재 대응 | idVendor/idProduct로 경로 재탐색 (수동) |
| 개선 | 리셋 유틸에 sysfs 자동 탐색 포함 |

### I-7. 두 스위치 동일 SSID/채널 (2스위치 환경)
| 항목 | 내용 |
|---|---|
| 현상 | host가 스캔에서 "스위치 A 선택"해도, ldn이 **SSID+채널**로 assoc → 같은 채널이면 스위치 B에 붙음 → 거부(status 1) |
| 증거 | dmesg: host assoc 대상 MAC = guest가 연결한 스위치 B의 MAC |
| 현재 대응 | 물리 분리 / 순차 기동 (연결된 스위치는 광고 중단 — 실측) |
| 개선 | **BSSID 기반 assoc** (`--target-bssid`, ldn 패치) — 같은 공간 테스트 필수 |

### I-8. 릴레이 세션 ID 불투명
| 항목 | 내용 |
|---|---|
| 현상 | host가 자동 생성한 세션 ID를 로그에서 못 찾음 (릴레이 access log에 응답 본문 없음) |
| 현재 대응 | curl로 세션 직접 생성 → host/guest에 --session-id 명시 (수동) |
| 개선 | 릴레이 로그에 세션 ID 표시 또는 `GET /sessions` 조회 API |

### I-9. 기타 (이전 세션 기록)
| 항목 | 내용 |
|---|---|
| ldn.scan VM hang (3회) | trio.with_timeout 래핑 필수 (메모리 기록) |
| 몬 파일 12개 → 6개 제한 | frlgtrade party 상한 — 와일드카드 사용 시 초과 에러 |
| 스위치 광고 중단 (세션 성립 시) | 실측: 연결된 스위치는 광고를 멈춤 → 순차 기동 시 유리 (기록 가치) |

---

## 3. 테스팅 프로세스 개선안 (권장 — 실행 전 체크리스트)

### 사전 준비 (스위치 켜기 전)
```
① 카드 감지: lsusb → USB ID로 카드 종류 확정 (8179=8188EU / 818b=8192EU)
② phy 감지: iw phy (자동 감지 유틸 권장)
③ NM 확인: 해당 카드 unmanaged or NM 중지 상태
④ stale vif 정리: phy의 모든 vif 삭제 (iw dev <name> del 반복)
⑤ 카드 생존: 비콘 tcpdump 3초 → 죽어있으면 authorized 토글 리셋
⑥ 스위치 확인: 스위치가 리더 대기 화면인지 확인
```

### 테스트 순서 (단독 테스트 — 이론 검증)
```
테스트 1: VM1 + 스위치A 단독 (다른 장비 전부 끔)
테스트 2: VM2 + 스위치B 단독 (다른 장비 전부 끔)
→ 둘 다 성공 = "동시 활성이 문제" 확정 → BSSID 패치로 해결
```

### 실패 시 진단 순서 (반복 실수 방지)
```
① 로그에서 실패 지점 확인 (saw 0 / status 1 / Match already / EBUSY / No such device)
② dmesg에서 무선 레벨 확인 (assoc 시도 있었는지, 어떤 MAC인지)
③ 카드 생존 확인 (비콘) — 죽었으면 리셋
④ vif 잔재 확인 (iw dev) — 있으면 정리
⑤ NM 상태 확인 (unmanaged 여부)
⑥ 재시도 (attempt 2~3에서 성공하는 패턴이 실제로 있음 — guest 실측)
```

---

## 4. 코드 개선 목록 (향후 — 지금은 적용 금지)

| # | 개선 | 난이도 | 효과 |
|---|---|---|---|
| C-1 | free_radio: udev rename된 vif 포함 정리 (phy 소속 전체) | 하 | I-1 근본 해결 |
| C-2 | phy 자동 감지 (USB ID → wiphy) | 하 | I-5 해결 |
| C-3 | NM conf를 interface-name 기준으로 (wlx*) | 하 | I-3 근본 해결 |
| C-4 | BSSID 기반 assoc (--target-bssid) | 중 | I-7 해결 (2스위치 필수) |
| C-5 | 릴레이 세션 조회 API / 로그 | 하 | I-8 해결 |
| C-6 | 카드 리셋 유틸 (sysfs 자동 탐색 + 토글) | 하 | I-4, I-6 해결 |
| C-7 | udev rename 방지 (net.ifnames=0) | 하 | I-2 근본 (선택) |
| C-8 | ldn.scan 타임아웃 래핑 (trio.with_timeout) | 하 | I-9 해결 |

---

## 5. 현재 상태 요약 (Audit 시점)

| 항목 | 상태 |
|---|---|
| 코드 | transport.py에 udev rename 패치(13줄) 미커밋. 그 외 커밋 6건 (Phase 2a 전체) |
| VM1 | 8192EU + rtl8xxxu, phy0, vif 없음, NM 중지됨, unmanaged conf 2개 MAC 포함 |
| VM2 (bridge-b) | 전원 분리 (테스트 1 준비) |
| 검증됨 | ① NM 중지 → Match already configured 해결 ② udev rename 패치 → No such device 해결 ③ join 성공 + Pia CONNECTED + RFU link UP (NI 단계에서 스위치가 disconnect — 별도 이슈) |
| 미해결 | NI handshake 중 스위치 disconnect (왜? — 다음 테스트에서 확인 필요) |

---

## 6. 결론

- **근본 문제는 카드/스위치가 아니라 "테스트 사이 정리 부재"** — 사전 체크리스트(§3) 도입으로 대부분 예방 가능
- 3건의 코드 개선(C-1, C-3, C-4)이 반복 실수를 원천 차단
- NI disconnect는 다음 테스트에서 "스위치 A 화면 상태"와 함께 재현/관찰 필요
