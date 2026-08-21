"""framerelay CLI - run one bridge half (docs/07-framerelay-design.md, Track B).

    sudo .venv/bin/python -m framerelay \
        --iface wlx00ada7117309 --host-mac 00:ad:a7:11:73:09 \
        --relay-url ws://RELAY:8000 --session-id AB12CD --role host --verbose

Needs root for the AF_PACKET monitor socket and a monitor-mode interface on the radio
that can see the local Switch. The other half runs identically next to the remote
Switch with --role guest. Both halves are transparent: frames in -> 0x20 -> WS ->
frames out; nothing about the trade is parsed or rewritten.

--relay-url may be the server base (the /session/<id>/ws?role=... path is appended) or a
full websocket endpoint. --host-mac is the LOCAL Switch's MAC (= LDN soft-AP BSSID); it
scopes capture to exactly that console so neighbor traffic is never relayed.
"""

import argparse
import os
import sys
import time

EMU_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if EMU_ROOT not in sys.path:
    sys.path.insert(0, EMU_ROOT)

from framerelay.bridge import RelayBridge           # noqa: E402
from framerelay.radio import MonitorRadio, parse_mac  # noqa: E402


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m framerelay",
        description="Transparent 802.11 <-> relay WebSocket bridge for remote Switch trades "
                    "(docs/07-framerelay-design.md)")
    parser.add_argument("--iface", required=True,
                        help="monitor-mode interface to capture/inject on (e.g. wlx00ada7117309)")
    parser.add_argument("--relay-url", required=True,
                        help="relay server base (ws://host:8000) or full /session/... ws endpoint")
    parser.add_argument("--session-id", required=True,
                        help="relay session id shared by both bridges")
    parser.add_argument("--role", choices=("host", "guest"), default="host",
                        help="relay slot of THIS bridge: host beside Switch A(leader), "
                             "guest beside Switch B(participant)")
    parser.add_argument("--host-mac", required=True,
                        help="LOCAL Switch's MAC (= LDN soft-AP BSSID) used as the capture filter")
    parser.add_argument("--verbose", action="store_true",
                        help="per-frame hex logs (default: milestones + stats only)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        host_mac = parse_mac(args.host_mac)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    radio = MonitorRadio(args.iface, host_mac=host_mac)
    app = RelayBridge(radio, args.relay_url, args.session_id,
                      role=args.role, verbose=args.verbose)
    try:
        app.start()
    except RuntimeError as e:               # AF_PACKET missing / bind failed etc.
        print(f"error: {e}", file=sys.stderr)
        return 1
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
