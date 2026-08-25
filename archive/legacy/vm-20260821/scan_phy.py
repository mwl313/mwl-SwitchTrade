#!/usr/bin/env python3
"""LDN 스캔 진단 스크립트 — hang 방지 (trio.with_timeout 30s).

용법: sudo /home/aria/ldnvenv/bin/python /home/aria/scan_phy.py [phyN]
- 반드시 timeout 래핑 + 백그라운드 실행 (무타임아웃 스캔은 VM 전체 hang — 3회 실측)
- 결과: found N / TIMEOUT / ERROR 중 하나를 출력
"""
import ldn, trio, time, sys, traceback


async def main():
    phyname = sys.argv[1] if len(sys.argv) > 1 else 'phy0'
    keys = ldn.load_keys('/root/.switch/prod.keys')
    t0 = time.time()
    print(f'[scan] starting on {phyname} (timeout 30s)', flush=True)
    try:
        with trio.fail_after(30):
            networks = await ldn.scan(keys, phyname=phyname)
        print(f'[scan] took {time.time()-t0:.2f}s, found {len(networks)}', flush=True)
        for n in networks:
            print(f'  comm_id=0x{n.local_communication_id:016x} ch={n.channel} '
                  f'band={n.band} accept={getattr(n, "accept_policy", "?")} '
                  f'parts={n.num_participants}/{n.max_participants}', flush=True)
    except trio.TooSlowError:
        print(f'[scan] TIMEOUT after 30s ({time.time()-t0:.1f}s elapsed) — still hanging', flush=True)
    except BaseException as e:
        print(f'[scan] ERROR: {type(e).__name__}: {str(e)[:300]}', flush=True)
        traceback.print_exc()


trio.run(main)
