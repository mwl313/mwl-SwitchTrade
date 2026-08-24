# 13 — 유저사이드 앱 플랜 & 프로덕션 병렬 트랙

> **2026-08-25 UI 결정 갱신:** frontend는 HTML/CSS이며 interaction에 필요한 최소 JavaScript만
> 사용한다. Python은 Windows/WSL 제어 backend 역할로 유지할 수 있고, pywebview/WebView2가 현재
> 최소 shell 후보다. 아래 PySide6 위젯 결정은 역사 기록이며 더 이상 frontend 기준이 아니다.

> 작성: 2026-08-22 | 상태: [확정] 언어·트랙 구조 결정, [실행] 트랙 α 착수
> 상위: `docs/06-distribution.md`(전략) · `docs/12-wsl2-poc-windows.md`(PoC 절차) · `docs/12-framerelay-구조와-로드맵.md`

## 0. 결정 요약

| 항목 | 결정 |
|---|---|
| 유저사이드 앱 | **HTML/CSS frontend + Python control backend** — WebView2 shell 후보 |
| 배포 형태 | SwitchTrade.exe 1개 (GUI = 첫실행 마법사 + 컨트롤 패널 겸용) |
| 프로덕션까지 병렬 트랙 | α(WSL2 무선) / β(배포 자동화) / γ(GUI 앱셸) / δ(릴레이 운영) |

---

## 1. 4병렬 트랙 (framerelay 앱 완성과 무관하게 지금 진행 가능)

필터 기준: framerelay E2E(STEP 12)에 의존하지 않는 것만 추림.

### α. WSL2 무선 기반 검증 (PoC G1~G4) ⭐ 최우선 — 지금 시작
- 로드맵 STEP 16 선행. framerelay 앱 불필요.
- **커널 빌드는 VM1(x86_64 Ubuntu)에서 수행** — WSL2 필요 없음. 산출물(bzImage+모듈)만 Windows로 전달.
- G3(RX)는 집 공유기(TP-Link 비콘)로 1차 검증 가능, G4(TX 인젝션)는 캡처 프레임 재주입→재캡처(V-1 방식 일반화)라 **동글 1개로 전 게이트 통과 가능**.
- 산출물 = 배포 번들 원형 (bzImage + 모듈 tar + 내장 펌웨어).
- 절차 상세: `docs/12-wsl2-poc-windows.md` Step 1~7.

### β. 배포 자동화 골격
- installer.ps1 사전 진단 모듈 (VT-x/SVM, Windows 버전) — 즉시 작성·테스트 가능
- 카드 사망 자동복구 PowerShell (usbipd detach/attach 사이클) — G2 후 실측
- 제거(원상복구) 스크립트

### γ. 유저사이드 앱 셸 (GUI) — Mock 브리지로 병렬 개발
- HTML/CSS 골격 + 화면 흐름 확정 (§4)
- GUI↔브리지 로컬 제어 프로토콜 명세 (wsl.exe 호출 래퍼)
- framerelay 완성 시 Mock → 실브리지 교체만 남는 구조

### δ. 릴레이 운영 준비
- relay/server.py Mac mini 상시 배포 + Cloudflare Tunnel 공개 (로드맵 14번 선행)
- 세션 ID 공유 UX 결정 (6자리 코드 vs QR)

```
α WSL2 무선 ──┐
β 배포자동화 ──┤ 병렬 ──▶ framerelay E2E 완료 시점 전부 합류 = 프로덕션
γ GUI 앱셸 ───┤
δ 릴레이 ─────┘
```

---

## 2. [역사 기록 — superseded] Python + PySide6 검토

판단 핵심: **브리지 로직은 어차피 WSL2 안의 Python**(radio.py/bridge.py). GUI는 조작 패널일 뿐 — 무선 처리·게임 해석·무거운 연산이 GUI에 없다. 단일 언어 스택의 이득 > 네이티브 미학.

| 후보 | 장점 | 단점 | 판정 |
|---|---|---|---|
| **Python + PySide6** ⭐ | 코드베이스 100% Python 통일 (브리지/릴레이/툴/GUI). 오픈코드 위임·검증 용이. PyInstaller exe 패키징 성숙 | exe 큼(~100MB), 네이티브 느낌 살짝 덜함 | ✅ 채택 |
| C# + WinUI3/Avalonia | 진짜 네이티브, 소형 바이너리 | 이중 코드베이스 — 유지보수 2벌 | 차선 (추후 리라이트) |
| Tauri (Rust+Web) | 초경량 | Rust 위임 부담 | 비추 |
| Electron | 생태계 | 과중 | 비추 |

> 프로젝트 원칙 "똑바로 작동 우선, 최적화는 마지막" — 네이티브 최적화는 최종 단계 과제.

## 3. 아키텍처

```
[Windows]
┌───────────────────────────────────────────┐
│ SwitchTrade.exe (Python + PySide6)        │ ← 사용자가 보는 유일한 것
│  ├─ 첫실행 마법사: 진단+설치 (β 흡수)       │
│  ├─ wsl.exe / usbipd.exe 제어 (관리자 승격) │
│  └─ 릴레이 WS 상태 구독 (진행상황 표시)      │
└─────────────┬─────────────────────────────┘
              │ wsl.exe 명령 · 파일 전달
┌─────────────▼─────────────────────────────┐
│ WSL2 (커스텀 bzImage + 모듈)                │
│  └─ framerelay bridge.py                  │
└─────────────┬─────────────────────────────┘
              │ MWLB/WS
     [릴레이 :8788] ⇄ [상대 브리지]
```
- installer.ps1은 별도 배포물이 아니라 **앱 첫실행 마법사가 내부 호출하는 모듈** — 사용자는 "앱 받아서 켜기" 한 번.
- 몬(.pk3)/키 파일은 브리지(WSL2) 로컬 유지 — 웹/클라우드 업로드 없음.

## 4. MVP 화면 명세 (γ 트랙 스코프)

| # | 화면 | 요소 |
|---|---|---|
| ① | 첫실행 마법사 | 가상화 진단 → WSL 설치 안내 → 커널 번들 배치 → 동글 연결 대기 → 완료 |
| ② | 메인 | 카드 생존(RX 카운터), 역할 선택(host/guest), 세션 코드 생성/입력, 시작 버튼 |
| ③ | 진행상황 | 연결됨 → 상대 참가 → 교환 중(N회차) → 완료 / 에러 상태 |
| ④ | 복구 | RX 정지 감지 → "복구" 버튼(usbipd 사이클) → 재확인. 수동 개입 1클릭 원칙 |

---

## 5. 트랙 α 실행 계획 & 역할 분담

### 아리아 파트 (Mac + VM1 — 지금 가능)
| # | 작업 | 상태 |
|---|---|---|
| A-1 | VM1에 WSL2-Linux-Kernel 클론 + CONFIG(CFG80211/MAC80211/RTL8XXXU=m + 펌웨어 내장) | 🔄 진행 |
| A-2 | bzImage + 모듈 tar 빌드 (INSTALL_MOD_PATH 격리 — VM 오염 없음) | ⏳ |
| A-3 | 배포 번들 초안 패키징 (.wslconfig 템플릿 + 설치 스크립트 초안) | ⏳ |
| A-4 | G1~G4 검증 명령 세트 + 결과 기록 양식 준비 | ⏳ |
| A-5 | γ 트랙: PySide6 골격 + Mock 브리지 (오픈코드 위임) | ⏳ |

### 주인님 파트 (Windows PC — 총 4단계, 예상 30분)
| # | 할 일 | 시간 |
|---|---|---|
| U-1 | 관리자 PowerShell에서 `wsl --install` → **재부팅 1회** (본인 확인 후) | 15분 |
| U-2 | 동글 꽂기 + usbipd 설치/attach (명령은 아리아가 BUSID 확인 후 전달) | 5분 |
| U-3 | 빌드 산출물(bzImage+모듈) 전달받아 배치 (전달 경로는 A-2 완료 시 확정 — VMware 공유폴더/scp/GitHub 중 택1) | 5분 |
| U-4 | 검증 명령 붙여넣고 출력 복사 (uname / modprobe / iw phy) | 5분 |

⚠️ 공통 주의: WSL 활성(Hyper-V 플랫폼) 시 VMware 성능 저하 가능 — V1/V2 관찰. Windows 절전 예방 powercfg 설정은 U-2 전 적용.

### 진행 순서
```
[A-1~2 빌드 (VM1)] ─▶ [U-1~4 Windows 검증 G1/G2] ─▶ [G3/G4 무선 검증] ─▶ [A-3 번들 확정]
        ▲ 이 문서 저장과 동시에 시작됨
```
