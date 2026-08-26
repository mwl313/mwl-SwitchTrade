# wsl2-kernel-build

> ⭐ **단일 진실(SSOT) 규칙 (2026-08-26 확정)**:
> **`MWL-SwitchTrade/scripts/wsl2/github-build`가 진실입니다.**
> - 수정은 항상 **그쪽(MWL 쪽)** 에서 하고, 확정 후 `wsl2-kernel-build`로 **그대로 복사**합니다.
> - 이 리포(`wsl2-kernel-build`)는 실제 Actions 빌드가 실행되는 **미러**로만 사용합니다.
> - 최신 상태 확인: `diff -r 이리포클론 MWL-SwitchTrade/scripts/wsl2/github-build` → 0건이면 동기화 완료.

MWL-SwitchTrade 배포용 WSL2 커스텀 커널 빌드 리포.
GitHub Actions가 microsoft/WSL2-Linux-Kernel을 받아 Wi-Fi 드라이버(rtl8xxxu)와
펌웨어(rtl8188eu/rtl8192eu — 커널에 내장)를 넣어 bzImage+모듈로 빌드한다.

사용: Actions 탭 → "Build WSL2 kernel" → Run workflow (기본값 OK)
결과: Artifacts에서 wsl2-kernel-runN 다운로드 (bzImage + modules tar + 설치 안내)

운영: 아리아 관리 (MWL-SwitchTrade 배포 트랙 α)
