"""External-radio check for the Vendor Action advertisement that drives LDN discovery.

Run this on VM2, never on the hosting radio. Keep an outer OS ``timeout`` because a
driver-level nl80211 hang cannot be interrupted by Trio.
"""

import argparse


COMM_ID = 0x01006FA0233F8000
SCENE_ID = 22287


def issues(network):
    """Return protocol mismatches that can make an FRLG client discard an advertisement."""
    app = bytes(getattr(network, "application_data", b"") or b"")
    checks = (
        (getattr(network, "local_communication_id", None) == COMM_ID, "comm_id"),
        (getattr(network, "scene_id", None) == SCENE_ID, "scene_id"),
        (getattr(network, "version", None) == 4, "ldn_version"),
        (getattr(network, "security_mode", None) == 1, "security_mode"),
        (getattr(network, "app_version", None) == 1, "app_version"),
        (getattr(network, "accept_policy", None) == 0, "accept_policy"),
        (getattr(network, "max_participants", None) == 6, "max_participants"),
        (len(app) == 122, "application_data_length"),
        (app[:5] == bytes.fromhex("005c160058"), "pia_header"),
    )
    return [name for ok, name in checks if not ok]


def describe(network):
    address = getattr(network, "address", "?")
    return (f"bssid={address} ch={getattr(network, 'channel', '?')} "
            f"comm=0x{getattr(network, 'local_communication_id', 0):016x} "
            f"scene={getattr(network, 'scene_id', '?')} "
            f"ldn=v{getattr(network, 'version', '?')}/security"
            f"{getattr(network, 'security_mode', '?')} "
            f"appver={getattr(network, 'app_version', '?')} "
            f"participants={getattr(network, 'num_participants', '?')}/"
            f"{getattr(network, 'max_participants', '?')} "
            f"appdata={len(bytes(getattr(network, 'application_data', b'') or b''))}B")


async def scan(args):
    import ldn
    import trio

    keys = ldn.load_keys(args.keys)
    with trio.fail_after(args.timeout):
        return await ldn.scan(
            keys, ifname=args.ifname, phyname=args.phy,
            channels=[args.channel], dwell_time=args.dwell)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keys", required=True)
    parser.add_argument("--phy", required=True)
    parser.add_argument("--channel", type=int, default=6)
    parser.add_argument("--ifname", default="ldn-ad-check")  # Linux IFNAMSIZ <= 15 chars
    parser.add_argument("--dwell", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args(argv)

    import trio
    try:
        networks = trio.run(scan, args)
    except trio.TooSlowError:
        raise SystemExit("FAIL: scan timed out; reset the radio before retrying")

    if not networks:
        raise SystemExit("FAIL: no decodable Nintendo Vendor Action advertisement received")
    valid = False
    for network in networks:
        mismatches = issues(network)
        print(describe(network), "OK" if not mismatches else f"MISMATCH={','.join(mismatches)}")
        valid |= not mismatches
    if not valid:
        raise SystemExit("FAIL: Action frames arrived but no exact FRLG host advertisement decoded")
    print("PASS: external radio decoded the exact FRLG Vendor Action advertisement")


if __name__ == "__main__":
    main()
