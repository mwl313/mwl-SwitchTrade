# Windows 11 VM: Python 3.14 설치 이후

물리 Windows PC는 Switch + managed WSL을 담당하고, VM은 RetroArch/gpSP와
네이티브 SwitchTrade Guest만 실행합니다. VM에 WSL이나 USB Wi-Fi 드라이버를
설치하거나 물리 Host의 USB Wi-Fi를 VM으로 넘기지 마세요.

설치와 설정은 먼저 진행할 수 있습니다. 실제 연결은 양쪽 소스 SHA와 해당 SHA의
Windows 3.12/3.14·Ubuntu CI, gpSP 최종 검증이 확인된 뒤 시작합니다.
이 안내는 실물 Pokémon 교환 성공을 주장하지 않습니다.

## 1. PowerShell 7과 Git 확인

이미 설치했다면 건너뜁니다. 없다면 VM 터미널에서:

```powershell
winget install --id Microsoft.PowerShell --exact --source winget --installer-type wix
winget install --id Git.Git --exact --source winget
```

공식 안내: [PowerShell](https://learn.microsoft.com/en-us/powershell/scripting/install/install-powershell-on-windows),
[Git](https://git-scm.com/install/windows).
설치 후 터미널을 새로 열고 **PowerShell 7**을 선택합니다.

```powershell
$PSVersionTable.PSVersion
git --version
py -3.14 --version
```

Python은 일반 Windows x64 CPython 3.14여야 합니다. free-threaded 빌드는 제외합니다.

## 2. SwitchTrade와 최소 의존성 설치

프로젝트를 둘 폴더에서 실행합니다. 아래 `switchtrade-gpsp` 폴더가 이미 있다면
덮어쓰지 말고 해당 폴더의 branch/status를 먼저 확인하세요.

```powershell
git clone --branch codex/gpsp-endpoint --single-branch https://github.com/mwl313/mwl-SwitchTrade.git switchtrade-gpsp
cd switchtrade-gpsp
git rev-parse HEAD
git status --short

py -3.14 -m venv .gpsp-venv
.\.gpsp-venv\Scripts\python.exe -m pip install --require-hashes -r requirements-gpsp.lock
.\.gpsp-venv\Scripts\python.exe -m pip check
```

오류가 나오면 다음 줄을 계속 실행하지 말고 오류를 확인합니다.
가상환경 활성화는 필요 없습니다. VM에서는 `dev.ps1 sync`나 일반 `requirements.txt`
설치를 하지 않습니다. 기존 `.gpsp-venv`가 있다면 버전을 확인하고 보존하세요.

## 3. 검증된 RetroArch와 gpSP 설치

[공식 1.22.2 Windows x64 배포 폴더](https://buildbot.libretro.com/stable/1.22.2/windows/x86_64/)에서
`RetroArch.7z`와 `RetroArch_cores.7z`를 받습니다.

1. RetroArch 압축을 새 폴더에 해제합니다. 기존 설치·설정·세이브를 덮어쓰지 않습니다.
2. cores 압축에서 `RetroArch-Win64/cores/gpsp_libretro.dll`만 꺼냅니다.
3. 사용할 `retroarch.exe` 옆의 `cores` 폴더에 그 DLL을 넣습니다.
4. 아래 해시와 일치하는지 확인합니다. Online Updater로 코어를 바꾸지 않습니다.

```text
RetroArch 1.22.2 / retroarch.exe SHA256
81c11b6f24932bf7918f05eee8928035bff3887335fd2a081507c75e9d94d06a

gpSP v1.0-74db5e6 / gpsp_libretro.dll SHA256
c84f619c1077a7fbae84c385df752fbeb867d301880400add7cce6a380dbd516
```

PowerShell에서 실제 경로에 맞춰 `Get-FileHash -Algorithm SHA256 '파일경로'`로 확인합니다.
단순히 표시 버전이 같은 다른 바이너리를 지원된 것으로 간주하지 않습니다.

## 4. RetroArch 설정과 실행 확인

사용자가 직접 RetroArch를 열고 gpSP 코어로 사용할 수 있는 FireRed/LeafGreen을
실행합니다. 첫 시험은 백업한 테스트용 세이브와 정상 속도로 진행하세요.

```text
Quick Menu → Core Options → Link Cable Connectivity → GBA Wireless Adapter
```

옵션을 수동 저장합니다. 콘텐츠 재로드가 필요하면 게임을 저장한 뒤 사용자가
직접 재로드합니다. Netplay의 연결 주소와 포트는 다음처럼 설정합니다.

```text
주소: 127.0.0.1
포트: 55435
```

이것은 VM 내부 연결 주소이며 Internet relay 주소가 아닙니다.
55435를 인터넷에 개방하지 않습니다. 게임을 켜둔 채 SwitchTrade 폴더에서:

```powershell
.\dev.ps1 doctor --emulator gpsp
```

doctor 성공은 프로세스/코어 확인이지 RFU나 게임 통신 성공이 아닙니다.
RetroArch가 여러 개 켜져 있으면 하나를 직접 종료하거나 의도한 PID를
`--emulator-pid`로 명시합니다. SwitchTrade는 게임을 자동 실행·리셋·종료하지 않습니다.

## 5. 연결 시작 전 공통 relay 확인

물리 Host 준비(등록 runtime, doctor/sync, 지정 USB, 키, radio gate)와
최종 CI 확인이 끝난 뒤 진행합니다. 양쪽 PowerShell 7에 같은 실제 Core relay 주소를 넣습니다.
아래 주소는 예시이므로 그대로 실행하지 마세요.

```powershell
$env:SWITCHTRADE_CORE_RELAY = 'https://실제-Core-relay-주소'
Invoke-RestMethod "$env:SWITCHTRADE_CORE_RELAY/core/health"
```

양쪽 모두 `status: ok`여야 합니다. 404면 legacy relay 또는 잘못된 경로이므로
여기서 멈춥니다. 서버 구축이 필요하면 [전체 runbook](GPSP_VMWARE_RUNBOOK.md)의
Common relay 절차를 별도 서버 운영자와 진행합니다. 인증서 검증을 끄지 않습니다.

## 6. 첫 번째 방

물리 Host에서:

```powershell
.\dev.ps1 run host --log-dir /opt/switchtrade-dev/logs/gpsp-host-01
```

6자리 Pair code와 `Waiting for a Group Leader room...` 안내가 나오면
**실물 Switch의 게임에서 Group Leader** 방을 만듭니다.

VM은 RetroArch/gpSP 게임을 켜둔 상태에서 실제 코드를 넣습니다. `123456`은 예시입니다.

```powershell
.\dev.ps1 run join 123456 --emulator gpsp --log-dir .qualification/physical-gpsp-01
```

1. `Connect RetroArch Netplay to 127.0.0.1:55435.` 안내를 확인합니다.
2. RetroArch에서 **Netplay → Connect**를 선택합니다. Netplay Host가 아닙니다.
3. SwitchTrade의 `Choose Join Group in the emulator.` 안내를 기다립니다.
4. 이제 **에뮬레이터 게임에서 Join Group**을 선택합니다.
5. 양쪽의 `Bridge active.`와 실제 게임 진행을 확인합니다.

`Bridge active.`만으로 Pokémon 교환 성공이라고 판단하지 않습니다.
양쪽 게임에 의도한 상대가 나타나고 같은 통신 동작이 정상 진행되는지 확인하세요.

## 7. 두 번째 방과 종료

Switch에서 방을 정상 종료하고 `Generation ended` / Pair 유지 안내를 확인합니다.
SwitchTrade와 RetroArch, 정상 로컬 Netplay 연결은 그대로 둡니다. Switch에서 새
Group Leader 방을 만들고, 새 안내 후 에뮬레이터에서 Join Group을 선택합니다.
정상 방 전환에는 새 Pair code나 프로그램 재시작이 필요 없어야 합니다.

시험을 끝낼 때 양쪽 SwitchTrade 터미널에서 Ctrl+C를 한 번 누르고 정리를 기다립니다.
RetroArch와 게임은 계속 실행돼 있어야 합니다. VM에서 확인:

```powershell
Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 55435
```

SwitchTrade 소유의 살아 있는 Listen/Established 연결은 없어야 합니다.
TIME_WAIT는 살아 있는 listener가 아닙니다. 조회 실패는 정리 완료의 증거가 아닙니다.
프로그램/전체 Pair를 종료했다면 다음 시험은 새 Host 코드로 시작합니다.

## 8. 오류가 나면

오류 직전 게임 동작·시간, 양쪽 SHA, RetroArch/core 해시와 양쪽
`switchtrade-core.log`를 남깁니다. cleanup 실패가 나오면 반복 실행하지 마세요.
Pair 코드/토큰, 개인 경로, 키 파일, ROM·세이브·Pokémon 데이터는 공개하지 않습니다.
물리 Host의 잔여 리소스 확인은 [Switch runbook](SWITCH_TO_SWITCH_PHYSICAL_RUNBOOK.md)을 따릅니다.
