# wsl2-kernel-build

MWL-SwitchTrade 배포용 WSL2 커스텀 커널 빌드 리포.
GitHub Actions가 microsoft/WSL2-Linux-Kernel을 받아 Wi-Fi 드라이버(rtl8xxxu)와
펌웨어(rtl8188eu/rtl8192eu — 커널에 내장)를 넣어 bzImage+모듈로 빌드한다.

사용: Actions 탭 → "Build WSL2 kernel" → Run workflow (기본값 OK)
결과: Artifacts에서 wsl2-kernel-runN 다운로드 (bzImage + modules tar + 설치 안내)

운영: 아리아 관리 (MWL-SwitchTrade 배포 트랙 α)
