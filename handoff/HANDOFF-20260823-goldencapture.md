# HANDOFF-20260823-goldencapture — 골든캡처 1차 결과와 다음 단계

> 작성: 아리아 (2026-08-23 저녁)
> 수신자: 코덱스 (분석 담당) + 다음 실기 검증 에이전트
> 관련: docs/20(코덱스 감사), docs/22(골든캡처 플레이북), docs/23(1차 결과)

---

## 1. 우리가 한 일 (타임라인)

1. **STEP 10 재정의**: 스위치 A·B끼리 직접 트레이드하는 세션을 PC가 옵저버로 캡처하는
   "골든캡처" 절차를 확립 (docs/22 플레이북).
2. **카드 페어 복구**: VM 재부팅 후 카드가 교차 배치된 것을 발견 → Windows PowerShell로
   호스트 상태 확인 후 올바른 페어(VM1=8192EU, VM2=8188EU)로 재배치.
3. **양방향 캡처 인프라 구축**:
   - VM1: 8192EU monitor CH6 → tcpdump pcap
   - VM2: 8188EU monitor CH6 → tcpdump pcap (단, fd 누수 이슈로 0B)
4. **골든캡처 실행**: 주인님이 스위치 A·B로 FRLG 다이렉트 커넥션 트레이드 시도.
   - 1회차: "교환 불가 포켓몬"으로 중단 (이 구간도 캡처에 포함 — 거절 패턴 데이터)
   - 2회차: 진행, 결과는 아래 분석으로.
5. **캡처 확보**: 44,807 프레임 / 9.7MB / 28분 / CH6 고정 / Mac+VM1 이중 백업.

## 2. 분석 방법 (재현 가능한 명령어)

```bash
# 프레임 수 확인
tcpdump -r golden_backup.pcap 2>/dev/null | wc -l

# 타입 분포 추출
tcpdump -r golden_backup.pcap -e 2>/dev/null > full.txt
grep -oE "Beacon|Probe|Auth|Assoc|Action|Data" full.txt | sort | uniq -c | sort -rn

# BSSID 분포 (누구의 네트워크였나)
grep -oE "BSSID:[0-9a-f:]+" full.txt | sort | uniq -c | sort -rn

# 스위치 MAC별 활동 (Probe Request 송신자 = 방 검색 중인 기기)
grep -iE "Probe Request" full.txt | grep -oE "SA:[0-9a-f:]+" | sort | uniq -c | sort -rn
```

## 3. 핵심 발견 — **LDN 프레임 0개**

| 타입 | 수량 | 정체 |
|---|---|---|
| Beacon | 21,752 | SK공유기(04/12/42:09:a5) + 이웃 공유기 |
| Data | 13,299 | **스위치→SK공유기 인터넷 통신** (CCMP IV 증가 = 실시간 암호화) |
| Probe Request | 341 | 공유기 탐색 (LDN용 아님) |
| Auth/Assoc | **0** | LDN 세션이 열리지 않음 |
| Nintendo Vendor Action | **0** | LDN 광고 없음 |

**BSS 전체가 SK공유기 계열. FRLG 로컬 무선(LDN) 세션이 캡처에 부재.**

## 4. 내 해석 (아리아의 생각)

### 유력 가설: NSO GBA 앱은 "다이렉트 커넥션"도 인터넷 경유를 먼저 시도한다

근거:
- 두 스위치 모두 SK공유기에 연결되어 있었고, 활발한 암호화 Data 교환이 있었음
- IV(Packet Number)가 연속 증가 = 끊김 없는 실시간 세션
- "교환 불가 포켓몬"으로 중단됐다는 사실은 **매칭 자체는 성공**했다는 뜻 → 무언가 연결은 됐음
- Kinnay 문서가 말하는 "진짜 로컬 LDN"이라면 Action 광고가 반드시 나왔어야 함

### 이게 맞다면 STEP 10의 전제가 흔들림

우리는 지금까지 "스위치가 로컬 무선(LDN)으로 방을 광고하고 찾는다"고 가정하고
ldn START_AP·beacon head·Vendor Action을 정밀하게 맞춰왔습니다. 그런데 NSO GBA 앱이
**공유기 LAN/인터넷 경유 매칭**을 우선 사용한다면:

- 스위치가 EMU 방을 못 찾은 게 아니라, **애초에 로컬 무선을 안 쓰고 있었던 것**
- ldn 스택 완성도와 무관하게, 앱이 온라인 모드일 때는 로컬 신호를 안 내보냄

### 검증 방법 (다음 실기)

**스위치의 Wi-Fi 연결을 끊거나 비행기 모드**로 설정 후 FRLG 다이렉트 커넥션 재시도:
- 인터넷 경로가 차단되면 앱은 진짜 로컬 무선(LDN)으로 폴백해야 함
- 이때 캡처하면 Vendor Action 광고가 나올 것 (docs/20 예측대로)
- 만약 비행기 모드에서도 통신이 안 되면 → NSO GBA 앱은 로컬 무선 미지원일 가능성
  → 이 경우 프로젝트 전략 재검토 필요 (docs/06 참조)

## 5. 데이터 위치

| 파일 | 위치 | 크기 |
|---|---|---|
| 원본 pcap | `logs/golden/golden_backup.pcap` (이 커밋, LFS 아님 - force add) | 9.7MB |
| Mac 백업 | `~/Projects/MWL-SwitchTrade/logs/golden/` | 동일 |
| VM1 백업 | `/home/aria/golden_backup.pcap` | 동일 |

분석용 전체 텍스트 덤프는 `/tmp/pcap_full.txt` (VM1) — 휘발성이라 필요시 재생성:
```bash
tcpdump -r logs/golden/golden_backup.pcap -e 2>/dev/null > full.txt
```

## 6. 코덱스에게 바라는 것

1. **pcap 심층 분석**: 위 명령어로 재현 가능. 특히 Data 프레임의 CCMP PN 패턴,
   QoS TID, DA가 공유기 MAC(`04:09:a5:0c:48:5d`)으로 고정인 점 확인 바람.
2. **NSO GBA 앱 동작 조사**: "다이렉트 커넥션"이 인터넷 릴레이를 쓰는지,
   로컬 무선 폴백 조건이 무엇인지 — Kinnay 문서 외 NSO GBA 관련 커뮤니티 자료.
3. **비행기 모드 실험 설계**: 로컬 폴백이 존재한다면 어떤 프레임이 나오는지
   캡처 체크리스트 갱신 (docs/22 §2 기준).

## 7. 현재 인프라 상태

- VM1: 카드 정상(monitor CH6), 코드 gptsolreview 배포됨, tcpdump 종료됨
- VM2: 카드 정상(monitor CH6), fd 누수는 재부팅으로 해결
- 캡처 도구: docs/22 플레이북 + advert_check 준비 완료
- 언제든 재캡처 가능
