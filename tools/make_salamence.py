#!/usr/bin/env python3
"""보만다 Lv100 .pk3 생성 — 꼬렛 기반 ID (DESTROY/40103/45851), 적법 세팅.
사용: python3 make_salamence.py <set으로_만든_중간.pk3> <출력.pk3>
"""
import sys, random
sys.path.insert(0, '/Users/leah/Projects/MWL-SwitchTrade/tools')
from stats import build_party_tail

SRC, DST = sys.argv[1], sys.argv[2]
mon = bytearray(open(SRC, 'rb').read())
assert len(mon) == 100, f"expected 100B party mon, got {len(mon)}"

# 1. PID → Adamant (Gen3 nature = PID % 25, Adamant = 3)
while True:
    pid = random.getrandbits(32)
    if pid % 25 == 3:
        break
mon[0:4] = pid.to_bytes(4, 'little')
print(f"PID: {pid:08X} -> nature 3 (Adamant)")

# 2. moves: Hidden Power(0xED), Earthquake(0x59), Dragon Dance(0x15E), Aerial Ace(0x14C)
#    Dragon Dance = Bagon Gen3 알 기술(egg move) — 부화 몬이면 적법 (리서치 확정 2026-08-21)
#    Aerial Ace = TM40 (Gen 3, Salamence 습득 가능)
moves = [0xED, 0x59, 0x15E, 0x14C]
for i, m in enumerate(moves):
    mon[44 + i*2 : 46 + i*2] = m.to_bytes(2, 'little')
print(f"moves: HP={moves[0]:04X} EQ={moves[1]:04X} DragonDance={moves[2]:04X} AerialAce={moves[3]:04X}")

# 3. IV: 비행 잠재파워 (Gen 3 최대 위력 35, T=8)
#    HP 테이블: 0=격투,1=비행,2=독... → 비행은 T∈[5,8]. 최대 T=8 = Spe만 홀수.
#    스모곤 공식 조합 "30/E/30/30/30/31" (E=30)과 동일. (2026-08-21 타입 테이블 수정)
ivs = [30, 30, 30, 31, 30, 30]  # hp, atk, def, spe, satk, sdef
iv_word = sum(v << (5*i) for i, v in enumerate(ivs))
mon[72:76] = iv_word.to_bytes(4, 'little')
print(f"IVs: {ivs} -> Hidden Power Flying (Gen3 max power 35, T=8)")

# 4. friendship 255 (growth offset: canon[41])
mon[41] = 255
print("friendship: 255")

# 5. 파티 테일 재구성 (Lv100 + 6스탯, nature 보정 포함)
tail = build_party_tail(bytes(mon))
mon[80:100] = tail
print("party tail rebuilt (Lv100 stats)")

# 6. 체크섬 재계산: secure [32:80] 16비트 워드 합 -> header [28:30]
cs = sum(int.from_bytes(mon[i:i+2], 'little') for i in range(32, 80, 2)) & 0xFFFF
mon[28:30] = cs.to_bytes(2, 'little')

open(DST, 'wb').write(mon)
print(f"wrote {DST} ({len(mon)}B) checksum=0x{cs:04X}")
