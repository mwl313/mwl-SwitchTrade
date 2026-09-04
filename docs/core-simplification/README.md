# SwitchTrade Core Simplification Planning Bundle

사용 순서:

1. `00_SWITCHTRADE_CORE_MASTER_PLAN.md`
2. `A_DEVELOPMENT_FOUNDATION_DESIGN.md`
3. `A_DEVELOPMENT_FOUNDATION_PROMPT.md`
4. Phase A 결과 검토
5. `B_CORE_FOUNDATION_DESIGN.md`
6. `B_CORE_FOUNDATION_PROMPT.md`
7. Phase B 결과 검토
8. `C_SWITCH_CORE_DESIGN.md`
9. `C_SWITCH_CORE_PROMPT.md`
10. Phase C 결과 검토
11. 그 후에만 D와 E 문서 작성

Phase 순서는 **A → B → C → D → E**로 고정한다.

- A: 문서 컨텍스트 축소 + installer 없는 source hot-deploy
- B: 하드웨어 독립 Pair/Generation Core
- C: 기존 Switch LDN/RFU 경로 연결
- D: 실물 안정화
- E: RetroArch gpSP 확장

Prompt 문서는 Terra/Luna에 전달할 수 있도록 작성되었다.
각 Prompt는 다음 Phase로 자동 진행하지 못하도록 stop gate를 포함한다.
