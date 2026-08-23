# HANDOFF-20260823 — 비WSL 완료 상태와 WSL 전환 테스트

> 작성: Codex, 2026-08-23
> 기준 커밋: `31cbd99` (`gptsolreview` 작업 트리)
> 목적: 검증된 VMware 환경을 보존하면서 WSL2 카드별 G2~G4를 조기 검증하고 안전한 배포 경로를 확정한다.

## 1. 비WSL 경로에서 완료한 것

### 무선/VM 기반

- VM1(`aria`, `100.109.113.113`) = RTL8192EU `0bda:818b`, MAC `a0:47:d7:b0:2b:39`.
- VM2(`bridge-b`, `100.115.7.43`) = RTL8188EU `0bda:8179`, MAC `00:ad:a7:11:73:09`.
- 두 카드 모두 `rtl8xxxu`, monitor mode, 실제 RX 통과, USB autosuspend 비활성(`power/control=on`).
- bridge-b NetworkManager 설정 복구 완료. `interface-name:wlx*`가 unmanaged이며 재부팅 후에도
  NetworkManager/systemd-networkd/Tailscale/Ethernet가 정상이다.
- 공통 `scripts/radio-health-gate.sh` 배포 완료. 캡처 전 1/6/11 실제 RX를 확인하고 RX 0일 때만
  선택한 USB 장치를 한 번 리셋한 뒤 재검증한다.
- `scripts/run_trade.sh`는 정상 카드를 매번 리셋하지 않고 health gate를 사용한다.
- VM/골든캡처/WSL/프레임 주입 runbook의 활성 캡처 절차는 health gate 래퍼를 사용한다.

### 프로토콜/캡처 기반

- 실제 Switch 광고에서 FireRed/LeafGreen `comm_id=0x01006fa0233f8000`, 참가자 `1/6`,
  LDN 후보 채널 1/6/11을 확인했다.
- EMU beacon/application-data 오류를 감사·수정했고 외부 카드 수신 검증 도구를 추가했다.
- 골든캡처 원본 `logs/golden/golden_backup.pcap`을 확보했다.
- 1차 골든캡처는 CH6 단일 관측이라 LDN 부재를 확정할 수 없다. 다음 Switch 실험은 인터넷 설정을
  제거하고 health gate 이후 1/6/11 discovery를 수행해야 한다.
- 프로덕션 방향은 EMU가 아니라 framerelay(투명 802.11 중계)이며, EMU는 기준/폴백이다.

## 2. WSL 현재 상태

- G1 통과: `6.6.123.2`와 `6.18.35.2-microsoft-standard-WSL2+` 빌드/부팅/모듈 검증 완료.
- 두 후보 모두 `vhci_hcd`, `rtl8xxxu`, `mac80211`, `cfg80211`, Realtek firmware 및
  `regulatory.db/.p7s`를 포함하며 기존 regulatory `-2` 오류가 사라졌다.
- **RTL8188EU G2 실패**: 6.6.87.2/6.6.123.2/6.18.35.2 모두 USB 열거와 firmware 로드는
  성공하지만 MCU ready가 오지 않아 약 3.6초 뒤 probe `-11`; `iw` interface가 없다.
- **RTL8192EU G2 + ambient G3 통과**: 같은 6.18.35.2/USB-IP에서 firmware start, monitor mode,
  CH1~13 설정, health gate 및 CH1/6/11 radiotap capture가 성공했다.
- 단순 커널 노후화와 WSL 전체 무선 불가 가설은 기각됐다. 현재 blocker는 8188EU와 USB/IP의
  firmware-start 상호작용이다.
- Windows WSL `2.7.12.0`, 기본 커널 계열 `6.18.33.2`, `usbipd-win 5.3.0`이며 5.3.0은
  2026-08-23 기준 최신 릴리스다.
- `usbipd-win` upstream issue #1022에도 native Linux/Windows에서는 정상인 Wi-Fi USB의 firmware
  upload가 USB/IP에서 실패한다. maintainer는 USB/IP 지연 또는 partial firmware upload로 판단했고
  issue는 아직 open이다. 따라서 WSL이 VMware보다 무조건 안정적이라는 가정은 현재 증거와 반대다.

## 3. 실행한 최소 전환 절차

1. VM2를 정상 종료해 disk 상태를 보존하고 RTL8188EU만 Windows로 반환한다. VM1/RTL8192EU는 건드리지 않는다.
2. Windows에서 8188EU의 실제 BUSID를 확인하고 `usbipd bind --busid` 후 WSL에 attach한다.
3. **G2**: `lsusb`, `dmesg`, `iw phy`, monitor interface 생성/채널 설정을 확인한다.
4. **G3**: health gate로 1/6/11 실제 RX를 확인하고 짧은 pcap을 남긴다.
5. **G4**: WSL 카드가 주입한 radiotap+802.11 frame을 VM1의 8192EU가 외부 재캡처하는지 확인한다.
6. 30~60분 RX soak 및 receive-death 복구를 측정한다. reset 후 USB/IP가 끊기면 Windows reattach가 필수다.
7. G2~G4와 soak가 통과한 뒤에만 WSL을 VM2 대체로 선언한다. 실패하면 VM2를 다시 켜 즉시 복귀한다.

## 4. 통과 기준

| Gate | 통과 기준 |
|---|---|
| G2 | 8192EU PASS: `0bda:818b`, `rtl8xxxu`, monitor mode, ch1~13 설정 성공. 8188EU FAIL |
| G3 | health gate PASS + 각 LDN 후보 채널에서 유효한 802.11 frame pcap 확보 |
| G4 | **8192EU PASS**: WSL TX frame을 VM2/8188EU가 외부 재캡처, 10 Hz 표본 90~93.3%, 수신 frame byte-exact |
| Soak | 30분 이상 연속 RX, 무응답이면 gate가 실패를 탐지하고 복구 경로가 결정적 |

8192EU의 G4는 통과했다. soak와 실제 Switch G5/G6 전에는 WSL이 VMware보다 안정적이라고 결론 내리지 않는다.

## 5. 실행 기록 — 2026-08-23 22:45~

- VM2를 soft shutdown했다. VM1은 계속 기준 수신기 역할을 한다.
- RTL8188EU는 Windows BUSID `4-14`로 복귀했고, `usbipd bind/attach` 후 WSL에서
  `0bda:8179`로 열거됐다.
- 설치된 6.6.87.2 커널 G2 결과: **FAIL**. firmware file 자체는 내장본으로 정상 로드됐지만
  매번 약 3.6초 후 `Firmware failed to start`, `probe ... failed with error -11`이 발생해
  `iw dev` interface가 생성되지 않았다.
- cold attach, driver reprobe, detach/attach를 합쳐 3회 재현했다. 수신 사망이나 NetworkManager
  문제가 아니라 USB/IP를 건넌 RTL8188EU MCU 시작 handshake 단계의 결정적 실패다.
- VMware USB Arbitrator가 WSL detach 직후 8188EU를 stub으로 선점하는 현상도 확인했다.
  bind/attach 동안 arbitrator를 멈추고 WSL attach 후 다시 시작하면 충돌을 피할 수 있다.
- VM1 VMX에는 `usb.autoConnect.device0 = "vid:0bda pid:818b"`를 추가했다. VM1은 다시
  RTL8192EU monitor CH6 실제 RX gate를 통과했다.
- VM2 VMX에도 rollback용 `vid:0bda pid:8179` 규칙을 추가했다. WSL 실패 시 detach 후 VM2를
  켜면 원래 카드만 다시 연결된다.
- 첫 Actions run `32643745625`는 잘못된 regulatory DB URL로 configure 단계에서 실패했고
  URL을 `wireless-regdb` upstream으로 수정했다. 재실행: 6.6.123.2 `32643887822`,
  비교용 6.18.35.2 `32643889920`.
- 두 수정 run은 모두 성공했다. 8188EU는 두 커널에서도 동일하게 firmware start `-11`로
  실패해 커널 노후화 가설을 기각했다. 두 버전의 `rtl8xxxu_start_firmware()`도 동일하다.
- 같은 6.18.35.2에서 RTL8192EU는 firmware start와 `iw` interface 생성에 성공했다.
  health gate PASS 후 CH1/6/11 5초 캡처에서 109/53/3 frames, kernel drop 0을 기록했다.
  산출물: `logs/wsl/g3-8192eu-ch1.pcap`, `g3-8192eu-ch6.pcap`, `g3-8192eu-ch11.pcap`.
- 8192EU는 1~13 모든 2.4GHz channel 설정에 성공했고 마지막에는 monitor CH6로 복원했다.
- G4 self-test는 radiotap probe request 20회 `send()`가 성공했지만 같은 카드 pcap에 echo가
  없었다. 송신 증명은 VM2/8188EU 외부 capture로 해야 한다.
- VM2 폴더는 Codex sandbox group에 read-only ACL만 있어 `.vmx.lck` 생성이 거부된다. 관리자
  child process에서도 ACL 변경이 `UnauthorizedAccessException`으로 차단됐다. 사용자가 VMware
  GUI에서 VM2를 시작하거나 해당 폴더에 Modify를 주면 즉시 외부 G4를 계속할 수 있다.
- kernel-build repo의 module archive는 다음 run부터 `INSTALL_MOD_STRIP=1`을 사용하도록
  `104ef11`에 수정·push했다. 현재 2.1~2.7GB 설치 크기를 release에서 줄인다.

2026-08-24 00:00 직전 상태:

- WSL: `6.18.35.2-microsoft-standard-WSL2+`, RTL8192EU attached, monitor CH6.
- RTL8188EU: Windows에 Shared 상태, VM2는 off.
- VM1: off. VMware USB Arbitrator: running.
- rollback: `C:\Users\임민우\.wslconfig.pre-6.6.123.2`, 기존 kernel/modules 보존.

참고 upstream:

- `usbipd-win` firmware upload timing/partial-upload issue:
  <https://github.com/dorssel/usbipd-win/issues/1022>
- 현재 설치된 `usbipd-win 5.3.0` 릴리스:
  <https://github.com/dorssel/usbipd-win/releases/tag/v5.3.0>

## 6. 후속 실행 기록 — 2026-08-24

- 사용자가 VM2를 다시 시작했다. VM2 `bridge-b`의 RTL8188EU는 `rtl8xxxu`, monitor CH6로
  정상 probe됐고 health gate actual RX를 통과했다. NetworkManager에서는 계속 unmanaged이며
  NetworkManager/systemd-networkd/Tailscale도 모두 active다. 카드가 물리적으로 고장 났거나
  영구 receive death에 빠졌다는 가설을 기각했다.
- WSL/RTL8192EU와 VM2/RTL8188EU를 모두 health gate로 CH6에 고정한 뒤 외부 G4를 완료했다.
  marker 100회 빠른 송신 중 42회가 외부 포착됐고 42/42 frame이 byte-exact였다.
- rate-relevant 10 Hz 실험은 30회 중 28 unique(93.3%), 100회 중 90 unique(90.0%), duplicate 0,
  포착 frame 전부 byte-exact였다. 수신 radiotap은 26바이트이며 bare 802.11 frame에는 FCS/padding
  변형이 없었다. 실험 직후 두 카드 health gate가 다시 통과해 지속 RX death/channel drift는 없었다.
- pcap: `logs/wsl/g4-wsl8192-to-vm8188.pcap`, `g4-wsl8192-to-vm8188-10hz.pcap`,
  `g4-wsl8192-to-vm8188-10hz-100.pcap`(git ignore, 로컬 보존).
- Windows USB selective suspend는 AC뿐 아니라 DC에서도 disabled로 통일했다.
- 첫 WSL soak는 20분/29,786 packets/0 kernel drops 후 background service만 남은 WSL instance가
  idle 종료됐다. radio는 재시작 즉시 정상이다. daemon 배포를 위해 `.wslconfig`에
  `instanceIdleTimeout=-1`과 `vmIdleTimeout=-1`을 추가했고 controlled restart 후 재검증한다.
- `SimplyCEO/rtl8188eus` commit `b5f02e742fad6ae27d893ffae62d05e27374c0ed`를 정확한
  6.18.35.2 WSL kernel tree에서 빌드하는 opt-in workflow를 kernel-build repo `f6f6739`에 추가했다.
  심화 감사 결과 mainline도 내부적으로 196-byte control transfer로 분할하므로 block 크기는 차이가
  아니다. vendor의 별도 MCU I/O wrapper reset, polling, firmware/init 흐름이 probe 결과를 바꾸는지
  실기로 확인한다.
- framerelay/beacon/radio safety 핵심 offline test 102개는 Windows audit venv에서 전부 통과했다.
- VM2 RTL8188EU soak는 00:24:48~00:49:08 KST 동안 24분 20초 실행돼 22,140 packets,
  filter 22,142 packets, kernel drop 0을 기록했다. 사용자가 VMware USB 메뉴 알림을 선택하면서
  `USB disconnect`로 중단됐으므로 30분 PASS로 과장하지 않는다. 카드는 현재 VM2 밖의 VMware
  stub에 대기 중이며, WSL vendor-driver probe 뒤 VM2로 복구한다.
- 전체 분석은 `docs/24-wsl-radio-validation-20260824.md`에 정리했다.

## 7. 최종 전환 결과

- idle 설정 적용 뒤 WSL/RTL8192EU 30분 soak가 41,394 packets/0 kernel drops로 통과했다.
- RTL8188EU는 mainline 실패와 달리 pinned vendor `8188eu`로 WSL monitor RX, CH1~13,
  외부 양방향 TX 및 probe/action/beacon/data injection을 통과했다.
- 두 카드는 WSL에 attach했고 VMware USB Arbitrator는 현재 session에서 정지했다. VM2는 무선 카드
  없이 Ethernet/Tailscale rollback 환경으로 정상 동작한다.
- profile-driven selector, Windows ownership preflight, role enforcement와 exact loaded-module 검증을
  구현했다. 상세 후속 인계는 `handoff/HANDOFF-20260824-wsl-dual-radio.md`를 기준으로 한다.
- framerelay double-radiotap 결함도 emulator commit `82dd0d3`에서 수정·push했다.
