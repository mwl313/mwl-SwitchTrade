# 24 — WSL/VM 무선 카드 검증 종합 보고서 (2026-08-24)

## 1. 결론

RTL8188EU 자체는 고장 나지 않았다. VM2를 재시작한 뒤 같은 카드(`0bda:8179`,
`00:ad:a7:11:73:09`)가 `rtl8xxxu`로 probe되고 monitor CH6에서 health gate와 실제 RF 수신을
통과했다. 따라서 EMU 성공 이후 나타난 현상은 카드의 영구 receive death가 아니다.

현재 실패 범위는 **이 PC의 WSL2 + usbipd-win/USB-IP + mainline `rtl8xxxu` + RTL8188EU** 조합이다.
USB 열거와 내장 firmware 검색까지 성공한 뒤 RTL8188EU MCU ready handshake가 약 3.6초 후
`-11`로 끝나므로 `iw` interface가 생성되지 않는다. NetworkManager, monitor mode, 채널, 캡처
스크립트가 개입하기 전 단계의 실패다.

반면 RTL8192EU(`0bda:818b`)는 같은 WSL, 같은 USB/IP, 같은 `rtl8xxxu`, 같은 커널에서 firmware
start, monitor RX, 채널 변경 및 외부 검증 TX injection을 통과했다. 따라서 "WSL에서는 USB Wi-Fi가
전부 안 된다"도 사실이 아니다.

검증 후 운영 구성은 다음과 같다.

- WSL RTL8192EU: in-kernel `rtl8xxxu`, host/guest/relay. G2~G4와 30분 soak 통과.
- WSL RTL8188EU: pinned vendor `8188eu`, guest/relay. G2~G4 통과; host는 과거 AP 미노출 실측으로 차단.
- VMware VM2는 Ethernet/Tailscale rollback 환경으로 보존하되 두 USB Wi-Fi 카드는 WSL이 소유한다.

## 2. RTL8188EU 실패 위치

| 단계 | WSL RTL8188EU | VM2 RTL8188EU | 의미 |
|---|---:|---:|---|
| USB 열거 | PASS | PASS | 케이블/포트/장치 식별 정상 |
| firmware 파일 접근 | PASS | PASS | firmware 누락 `-2` 문제 해결됨 |
| firmware MCU start | **FAIL (`-11`)** | PASS | WSL USB/IP 전송/타이밍 경계 |
| `iw` interface 생성 | 미도달 | PASS | NetworkManager 이전 실패 |
| monitor mode/channel | 미도달 | PASS | 채널 설정이 원인 아님 |
| 실제 RX | 미도달 | PASS | receive death와 다른 실패 |

위 표의 WSL 열은 **mainline `rtl8xxxu` 경로**다. pinned vendor `8188eu` 경로에서는 interface,
monitor, CH1~13, 실제 RX와 외부 TX가 모두 통과했다.

WSL에서 6.6.87.2, 6.6.123.2, 6.18.35.2 세 커널이 같은 지점에서 실패했다. 따라서 단순히
커널을 최신으로 올리거나 regdb/NetworkManager/채널 설정을 바꾸는 것으로는 해결되지 않는다.

`usbipd-win`의 open issue #1022에도 native Linux에서는 정상인 USB Wi-Fi가 USB/IP에서 firmware
upload/start에 실패하는 사례가 있고, maintainer는 USB/IP 지연 또는 일부 firmware 전송 누락을
의심한다. 현재 설치 버전은 최신 `usbipd-win 5.3.0`이므로 이미 릴리스된 단순 업그레이드 해결책은
없다. 다만 이 장치의 mainline log는 `Firmware checksum poll timed out`이 아니라 그 다음 단계의
`Firmware failed to start`다. 즉 device checksum report는 왔고 `WINT_INIT_READY`가 오지 않은
것으로, #1022의 partial-upload 설명은 유사 사례이지 이 카드 원인의 확정 증거가 아니다.

## 3. WSL RTL8192EU G4 외부 RF 검증

단일 카드의 `send()` 성공은 RF 송신 증명이 아니므로 VM2 RTL8188EU를 외부 수신기로 사용했다.
두 카드 모두 health gate 통과 후 CH6에 고정했다.

| 실험 | WSL 송신 | VM2 외부 캡처 | 결과 |
|---|---:|---:|---|
| 빠른 marker probe | 100 | 42 | marker 42, payload 42/42 byte-exact |
| 10 Hz 짧은 표본 | 30 | 28 unique | 93.3%, duplicate 0, 28/28 byte-exact |
| 10 Hz 100-frame 표본 | 100 | 90 unique | 90.0%, duplicate 0, 90/90 byte-exact |

외부 수신 radiotap은 26바이트였지만 radiotap을 제외한 802.11 frame은 송신본과 정확히 같았고
FCS/padding 변형도 없었다. 100-frame 실험 뒤 두 카드 health gate가 즉시 다시 통과했으므로 이
손실은 지속적인 RX death나 채널 drift로 설명되지 않는다.

이 수치는 broadcast Probe Request의 무응답 단방향 표본이다. 실제 LDN beacon은 반복 송신되고,
unicast data에는 ACK/retry가 있으므로 90%를 곧바로 LDN 데이터 신뢰도로 해석하면 안 된다. 반대로
SIFS ACK를 인터넷 왕복으로 대체할 수 있다는 증거도 아니다. G5/G6와 실제 Switch 세션은 별도
게이트로 남는다.

로컬 보존 pcap(의도적으로 git ignore):

- `logs/wsl/g4-wsl8192-to-vm8188.pcap`
- `logs/wsl/g4-wsl8192-to-vm8188-10hz.pcap`
- `logs/wsl/g4-wsl8192-to-vm8188-10hz-100.pcap`

## 4. WSL RTL8188EU vendor-driver 검증

`SimplyCEO/rtl8188eus` commit `b5f02e742fad6ae27d893ffae62d05e27374c0ed`를 정확한
`6.18.35.2-microsoft-standard-WSL2+` tree에서 빌드했다. module `vermagic`와 실행 kernel이
일치하며 mainline에서 `-11`로 unbound된 동일 장치를 `8188eu`가 정상 claim했다.

| 실험 | 결과 |
|---|---|
| monitor + CH1~13 | 전 채널 setter와 actual-RX PASS |
| 8192EU → 8188EU | 86/100 unique, duplicate 0, 주소/payload exact, receiver-added FCS 4B |
| 8188EU → 8192EU | 98/100 unique, duplicate 0, Sequence Control 외 주소/payload exact |
| frame type 각 25회 | probe 24, vendor action 24, beacon 25, data 25, kernel drop 0 |

Sequence Control overwrite와 beacon timestamp 갱신은 장치가 over-air management frame에서 소유하는
필드다. application payload/주소 손상 증거는 없다. 첫 module은 Linux 6.18에서 금지된 direct
`dev_addr` write 때문에 interface open 시 warning을 냈다. kernel-build commit `1650687`은 여섯
write를 `eth_hw_addr_set()`으로 바꾸며 warning-free rebuild를 최종 재검증한다.

`usb 1-2: seqnum max` 한 줄은 driver error가 아니다. Linux `vhci_hcd`가 USB/IP URB sequence가
`0xffff`일 때 출력하는 informational message이며, 그 뒤 실제 RX/TX가 계속 통과했다.

## 5. 영구 운영 경로

1. **기본 지원 경로 — RTL8192EU를 WSL에 사용**
   in-kernel driver로 WSL G2~G4와 30분 soak를 통과한 기본 카드다. 유지보수와 rollback이 가장
   간단하며 host/guest/relay 전 역할 후보다.
2. **RTL8188EU pinned vendor driver**
   mainline `rtl8xxxu`와 다른 firmware upload/start 경로를 쓰는 `8188eu` 모듈이 USB/IP 타이밍
   문제를 우회할 가능성이 있다. `SimplyCEO/rtl8188eus`의
   `b5f02e742fad6ae27d893ffae62d05e27374c0ed`를 정확한 WSL 6.18.35.2 kernel tree에서 빌드하는
   reproducible workflow를 추가했다. probe/monitor/RX/injection은 통과했으며 patched module
   warning gate 뒤 guest/relay profile로만 배포한다. 심화 코드 감사에서 두 드라이버 모두
   4096바이트 firmware page를 실제로는 196바이트
   이하 USB control transfer로 분할함을 확인했다. 따라서 transfer block 크기는 우회 근거가 아니다.
   실험 근거는 vendor가 MCU I/O wrapper까지 reset하는 별도 8051 sequence, wall-clock/yield 기반
   ready polling, 내장 firmware 및 전체 초기화 흐름을 쓴다는 점이다. 실기 결과 이 경로가
   USB/IP MCU-start 실패를 우회했다.
3. **upstream 수정 대기/기여**
   usbipd-win 또는 Linux USB/IP/driver 쪽 firmware-transfer 문제가 해결되면 mainline 경로가 가장
   유지보수하기 좋다. 현재 공개된 확정 수정은 없다.
4. **하드웨어 교체**
   장기 배포 카드에는 USB/IP에서 monitor RX와 injection을 실제 통과한 모델만 허용한다. 단순히
   "Linux 지원" 또는 "5 GHz 지원" 표기만으로 WSL 호환을 가정하지 않는다.

## 6. 시스템 감사 결과

- VM2는 실행 중이며 Ethernet/Tailscale과 NetworkManager/systemd-networkd가 정상이지만 USB Wi-Fi는
  소유하지 않는다.
- WSL은 RTL8192EU BUSID `4-18`과 RTL8188EU BUSID `4-14`를 모두 attach하고 있다.
- VM2의 NetworkManager, systemd-networkd, Tailscale은 모두 active이고 monitor interface는
  NetworkManager에서 unmanaged다.
- VMware USB Arbitrator는 WSL dual-radio 운영 중 정지 상태다. start type은 Automatic이므로 reboot
  후 `scripts/windows/wsl-radio-preflight.ps1 -Prepare -AutoAttach`를 elevated PowerShell에서
  실행한다. 현재 두 BUSID에는 hidden usbipd auto-attach watcher가 하나씩 동작 중이다.
- Windows USB selective suspend는 AC/DC 모두 disabled로 통일했다.
- WSL `.wslconfig`는 `C:\wsl-kernel\bzImage-wsl-st-6.18.35.2`를 사용한다. 기존 kernel/modules와
  `.wslconfig.pre-6.6.123.2` rollback을 보존했다.
- 최초 WSL soak는 background systemd service만 남긴 상태에서 20분 후 WSL instance가 종료돼
  29,786 packets/0 kernel drops에서 끝났다. radio failure가 아니라 WSL lifecycle 문제이며 daemon
  배포 blocker다. `.wslconfig`에 `[general] instanceIdleTimeout=-1`과
  `[wsl2] vmIdleTimeout=-1`을 추가하고 controlled shutdown/restart로 적용했다. 최종 soak는
  정확히 30분/41,394 packets/0 kernel drops로 통과했다.
- 캡처/주입 시작 전 `scripts/radio-health-gate.sh`를 반드시 사용한다. 기본 1/6/11은 빠른 건강
  확인용이고, 실제 discovery는 필요 시 `--health-channels 1,2,3,4,5,6,7,8,9,10,11,12,13`으로
  전 채널을 순회할 수 있다.
- 현재 health gate는 주변의 실제 802.11 frame 한 개를 수신해야 PASS한다. RF가 완전히 조용한
  장소에서는 정상 카드도 실패로 판정할 수 있으므로 배포판에서는 "외부 test transmitter" 또는
  "실패하되 자동 reset하지 않는 진단 모드"를 추가 검토한다. 현재처럼 주변 traffic이 있는 실험실
  검증에는 실제 RX를 증명한다는 장점이 더 크다.
- `config/wsl-radio-hardware.tsv`와 `wsl-radio-prepare.sh`는 USB ID/driver/module/vermagic/SHA/role를
  검증한다. 여러 지원 카드가 있으면 ID를 지정하지 않은 실행을 거부하며 실제 RX 뒤 command를 exec한다.
- framerelay double-radiotap 결함을 수정했다. bridge는 bare 802.11 frame을 전달하고
  `MonitorRadio.send()`가 radiotap을 정확히 한 번만 붙인다(emulator commit `82dd0d3`).

## 7. 남은 게이트

- patched vendor `8188eu` artifact의 warning-free load + 짧은 actual RX/TX 재검증.
- 인터넷 설정을 제거한 Switch 두 대로 1~13 discovery capture. 단, 한 카드 호핑은 각 채널 체류
  시간 밖의 frame을 놓치므로 가능하면 여러 카드 고정 캡처 또는 반복 실험을 함께 사용한다.
- framerelay G5 로컬 루프와 G6 실제 Switch E2E. 특히 ACK/retry와 SIFS 경계를 측정한다.

## 8. 소프트웨어 회귀 확인

기존 핵심 offline test 102개가 통과했다. 이번 radiotap/selector 수정 뒤 Linux focused suite
58개도 통과했다. 전체 discover는 115 assertions가 통과했고 standalone related-repo clone의
`test_relay_offline`만 parent `relay/` layout을 가정해 setup error가 났다. product assertion 실패는
아니며 main SwitchTrade checkout layout에서 실행하는 integration test다.

## 9. 참고

- usbipd-win firmware upload issue: <https://github.com/dorssel/usbipd-win/issues/1022>
- usbipd-win 5.3.0: <https://github.com/dorssel/usbipd-win/releases/tag/v5.3.0>
- vendor driver 후보: <https://github.com/SimplyCEO/rtl8188eus>
- WSL kernel `rtl8xxxu` firmware path:
  <https://github.com/microsoft/WSL2-Linux-Kernel/blob/linux-msft-wsl-6.18.35.2/drivers/net/wireless/realtek/rtl8xxxu/core.c#L1945-L2112>
- mainline RTL8188EU reset + 196-byte block setting:
  <https://github.com/microsoft/WSL2-Linux-Kernel/blob/linux-msft-wsl-6.18.35.2/drivers/net/wireless/realtek/rtl8xxxu/8188e.c#L558-L577>
  <https://github.com/microsoft/WSL2-Linux-Kernel/blob/linux-msft-wsl-6.18.35.2/drivers/net/wireless/realtek/rtl8xxxu/8188e.c#L1835-L1868>
- vendor MCU reset/poll path:
  <https://github.com/SimplyCEO/rtl8188eus/blob/b5f02e742fad6ae27d893ffae62d05e27374c0ed/hal/rtl8188e/rtl8188e_hal_init.c#L564-L843>
- USB/IP `seqnum max` source:
  <https://github.com/torvalds/linux/blob/master/drivers/usb/usbip/vhci_hcd.c>
