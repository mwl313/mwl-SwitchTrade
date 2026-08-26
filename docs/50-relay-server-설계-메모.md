# 24 — 릴레이 서버 아키텍처 & 배포 설계 (2026-08-24)

> 작성: 아리아 | 상태 태그: [확정] = 결정됨 / [방향] = 검토 필요 / [미결] = 결정 필요
> 상위: `docs/06-distribution.md` §8(배포 전략) · `docs/12-framerelay-구조와-로드맵.md`(STEP 14 2c 인터넷 배포)
>       · `docs/13-userside-app-plan.md` §δ(릴레이 운영 준비)

---

## 0. 한눈 요약

| 항목 | 결정 |
|---|---|
| 역할 | FRLG LDN 투명 중계 — MWLB/WS 바이트 파이프 (내용 해석 없음, 비상태 원칙) |
| 오리진 순위 | **① Oracle Always Free (ap-tokyo-1, 2 OCPU/12GB)** 확보 시 → **② Mac mini 임시 오리진** (확보 전까지, 주인님 승인 2026-08-24) |
| 공개 경로 | `relay.minwoolim.com` — Cloudflare Tunnel 기반 WSS(443), **포트 직접 개방 없음** |
| 스토리지 | **SQLite(`relay.db`) 1파일** — 방 리스트 + 트레이드 통계 영속. 이식 = 파일 복사 1개 |
| 세션 제한 | MAX_SESSIONS = **800** (egress 10TB/월 보호) |
| 상태 | Oracle 그랩 폴링 진행 중 (`MWL-OracleGrab`, 24/7) |

---

## 1. 아키텍처

```
[Switch A] ←802.11→ [브리지A] ←MWLB/WS(WSS)→ [cloudflared] → relay.server:8788 (127.0.0.1)
                                                      │
                                                 relay.db (SQLite)
                                                      │
[Switch B] ←802.11→ [브리지B] ←MWLB/WS(WSS)→ [cloudflared] ←─┘
```

- **세션(방)은 메모리가 원본** — 실시간 중계 경로에 DB 개입 없음 (지연에 영향 0)
- **DB는 영속 메타 전용**: 공개방 목록 조회 + 트레이드 통계 기록
- 브리지/스위치는 기존과 동일 — 클라이언트는 `wss://relay.minwoolim.com`만 알면 됨

## 2. 용량 산정 (2026-08-24 실측 기준)

| 지표 | 값 | 근거 |
|---|---|---|
| 세션당 트래픽 | 평균 2~8KB/s (비콘 재생 ~1.5KB/s + 게임 데이터) | LDN 프레임 크기 분석 |
| Mac mini 업로드 | **47MB/s (≈376Mbps) 실측** | `speed.cloudflare.com` 8MB POST |
| Mac mini 안전권 | **동시 1,000~2,000세션** (CPU·RAM 1~3% 수준) | M2 8코어/16GB, 세션당 수십 KB |
| Mac mini 이론 한계 | ~4,700세션 | 대역폭만으로 (10KB/s/세션) |
| Oracle egress | 10TB/월 무료 = 평균 3.9MB/s → 상시 기준 동시 ~780세션 | Oracle 공식 Always Free |
| Oracle 안전권 | 500세션 피크 여유 (일 6시간 기준 월 2~8TB) | 상한 800과 일치 |

**결론: 스펙 병목 없음. 세션 상한 800이 유일한 수제 한계.**

## 3. 스토리지 설계 (신규 — 방 리스트 + 트레이드 통계)

### 3.1 DB 옵션 비교 (2026-08-24 검토)

| 옵션 | 장점 | 단점 | 판정 |
|---|---|---|---|
| **SQLite (WAL)** | 프로세스 0 · 백업/이식 = 파일 1개 · 쓰기 1건/세션이라 수만 건/일도 여유 | 다중 프로세스 쓰기 제한(우리는 서버 1개라 무관) · 원격 접속 불가 · 복잡 집계 시 SQLite 만의 한계 | ⭐ **지금 정답** |
| **PostgreSQL** | 강한 동시성·윈도우함수·JSONB·전문검색 · **원격 접속**(GUI/대시보드) · 멀티 오리진(서버 여러 대)시 스키마 공유 | 프로세스·RAM 추가(100~200MB) · 백업=pg_dump/복원 · 패치·업데이트 운영 부담 · 이식이 파일 복사보다 복잡 | 조건부 — 아래 트리거 충족 시 |
| MySQL/MariaDB | PG와 유사 | PG에 비해 특별한 이점 없음 | 비추 |
| 파일(JSONL) | 가장 단순 | 조회·집계 불가, 동시성 0 | 비추 |

**PostgreSQL이 이득이 되는 순간 (트리거):**
1. 통계를 **여러 클라이언트(GUI 앱·관리자 대시보드)가 실시간으로 조회** (SQLite는 파일 잠금·동시 읽기 제약)
2. **멀티 오리진** — 리전별 릴레이 서버 여러 대가 한 DB에 기록 (통합 통계)
3. 사용자 계정·닉네임·랭킹·리더보드 등 도메인 확장 (외래키·조인 필요)
4. 월별 유저별 복잡한 집계/윈도우 함수 분석 (SQLite 대신 PG 쿼리력)

**하이브리드 전략 [방향 — 권장]:**
- **SQLite로 시작** + 스키마를 **PG 호환 표준 SQL(TEXT/INTEGER/BIGINT만)** 로 작성 → 추후 pg_dump/login 없이 이관 스크립트 `CREATE TABLE` 재생성만
- 오라클 VM은 12GB/2 OCPU라 PG(100~200MB) 돌릴 리소스는 충분 — **리소스가 아니라 운영 복잡도**가 판단 기준
- 이전 트리거: 일일 통계 기록 1,000건 초과 or GUI 대시보드 조회 도입 or 멀티오리진 → 그때 Docker PG 이관 (30분 작업, 데이터는 마이그레이션 스크립트로)

### 3.2 테이블 초안

```sql
-- 공개방 목록 (실시간 상태는 메모리 세션이 원본 — DB는 조회·감사용)
CREATE TABLE rooms (
  session_id  TEXT PRIMARY KEY,
  created_at  INTEGER NOT NULL,        -- Unix sec
  last_active INTEGER NOT NULL,
  host_role   TEXT,                    -- 'host' | 'guest' (브리지 초기화 롤)
  status      TEXT NOT NULL DEFAULT 'open',  -- open|closed
  ended_at    INTEGER
);

-- 트레이드 통계 (완료/중단 시 1건 기록)
CREATE TABLE trade_stats (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id   TEXT NOT NULL,
  started_at   INTEGER NOT NULL,
  ended_at     INTEGER NOT NULL,
  duration_s   INTEGER NOT NULL,
  bytes_relayed INTEGER NOT NULL,      -- /metrics 기반 서버 파생
  result       TEXT NOT NULL,           -- completed|peer_offline|timeout
  pokemon_traded INTEGER                -- [미결] 브리지 리포트 시 채움
);
```

### 3.3 통계 수집 방식 — [미결] (주인님 결정 필요)

서버는 프레임을 해석하지 않으므로 **서버만으로 파생 가능한 것**과 **브리지가 리포트해야 하는 것**이 나뉘어요:

| 유형 | 항목 | 수집 주체 |
|---|---|---|
| 서버 자체 파생 | 세션 수, 세션 길이, bytes_relayed, result(완료/중단) | relay.server.py |
| **브리지 리포트** ⭐ | 교환 마리수, 포켓몬 종류, 완료 여부 | 브리지가 별도 엔드포인트로 POST (예: `/session/{sid}/stats`) |

기본안: **서버 파생 통계만 먼저 쌓고**, 브리지 리포트는 GUI 앱(γ 트랙)이 완성될 때 붙이는 것을 권장.

### 3.4 백업 [방향]
- 일일 1회 `relay.db` (+`-wal`) 복사 → `relay-backup/` 14일 보존, cron 등록
- Oracle 이식 시 백업 파일 그대로 복사 → 무중단 전환

## 4. 배포 플로우

| Phase | 내용 | 상태 |
|---|---|---|
| M1 | Mac mini 임시 오리진: relay launchd + `relay.minwoolim.com` 터널 인그레스 (cloudflared 리로드 1~2초) | ⬜ 승인 대기 |
| M2 | server.py v2: 공개방 목록 API(`GET /rooms`) + 통계 기록(3.2/3.3) + SQLite | ⬜ 개발 |
| O1 | 오라클 확보 → git clone + systemd + cloudflared **다중 커넥터**(동일 터널 토큰) → 무중단 전환 | ⬜ 그랩 대기중 |
| O2 | 이식 완료 후 Mac mini 임시 종료 + 그랩 워치 정리 | ⬜ |
| O3 | Budget $10 + 100% 알림 — ✅ 완료 (2026-08-26): `mwl-relay-safety` Budget + Alert(minwlim72@gmail.com), A1 한도 2/12 할당 확인 | ✅ |

> 리포 분리 (2026-08-26): 서버 인프라 전체는 **`MWL-SwitchTradeServer`** 단독 리포로 이동 (relay/·deploy/·tools/oraclegrab/·docs/01). 클라이언트(MWL-SwitchTrade production-beta)는 이 설계의 URL만 바라봄.

### 이식 원칙
- 이동 물품: **코드(git) + relay.db 1파일 + 서비스 유닛(5줄)** — 데이터 마이그레이션=파일 복사
- 클라이언트(브리지)는 URL 불변 → 사용자 인지 없음
- cloudflared 다중 커넥터 사용 시 **Mac mini ↔ Oracle 이중화**도 가능 (한쪽 죽으면 자동 전환)

## 5. 보안 & 제약

- 8788은 `127.0.0.1` 바인드 (터널 통해서만 접근)
- DB 로컬 전용, 외부 노출 없음
- 세션 상한 800 (egress 보호) + `/metrics` 모니터 (bytes_relayed 누적 확인)
- **Mac mini 임시 오리진은 "오라클 확보 전까지" 한정** — 원칙("Mac mini/미니DC 절대X") 예외는 임시에만

## 6. 대기 중 결정 (미결)

1. cloudflared 리로드 승인 (hermes.minwoolim.com 1~2초 단절) — 진행 여부
2. **트레이드 통계 필드**: 서버 자체 파생만? + 브리지 리포트(교환 마리수 등)까지?
3. Budget 알림 수신 이메일 (오라클 계정 이메일)
4. 공개방 목록 UI/API 형태 (`GET /rooms` JSON으로 시작, GUI는 γ 트랙에서)
