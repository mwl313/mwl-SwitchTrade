# wsl2-kernel-build

> **단일 진실(SSOT):** `MWL-SwitchTrade/scripts/wsl2/github-build`에서 수정·검증한 뒤
> 이 실행 미러에 동일하게 반영합니다. 두 위치의 추적 파일이 일치해야 동기화 완료입니다.

MWL-SwitchTrade 배포용 WSL2 커스텀 커널 빌드 리포.
GitHub Actions가 microsoft/WSL2-Linux-Kernel을 받아 Wi-Fi 드라이버(rtl8xxxu)와
펌웨어(rtl8188eu/rtl8192eu — 커널에 내장)를 넣어 bzImage+모듈로 빌드한다.

사용: Actions 탭 → "Build WSL2 kernel" → Run workflow (기본값은 실기 검증 기준 `linux-msft-wsl-6.18.35.2`)
결과: Artifacts에서 wsl2-kernel-runN 다운로드 (bzImage + modules tar + 해시 manifest + 설치 안내)

새로운 in-kernel 카드 지원은 `extra_kernel_config`에 공백 구분
`CONFIG_DRIVER=m` 항목을, firmware가 필요하면 `extra_firmware`에
`vendor/file.bin=https://...` 항목을 추가한다. symbol/value와 상대경로를 검증하며
`olddefconfig`가 요청을 바꾸면 build를 실패시킨다.

`include_vendor_8188eu=true`는 RTL8188EU의 WSL USB/IP firmware-start 문제를 진단하기 위한
opt-in 실험이다. `SimplyCEO/rtl8188eus` commit
`b5f02e742fad6ae27d893ffae62d05e27374c0ed`를 같은 kernel build tree에 대해 컴파일하고
Linux 6.18의 netdev address bookkeeping에 맞춘 로컬 patch를 적용한 뒤
`8188eu-vendor.ko`를 추가한다. 기본값은 false이며 G2~G4 실기 통과 전에는 배포 기본 드라이버가
아니다. 원본 commit과 로컬 patch를 모두 고정하므로 같은 산출물을 재현할 수 있다.

운영: 아리아 관리 (MWL-SwitchTrade 배포 트랙 α)
