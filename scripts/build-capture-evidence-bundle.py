#!/usr/bin/env python3
"""Build a documented, self-contained SwitchTrade capture evidence bundle."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import sys
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
PCAP_MAGICS = {
    b"\xd4\xc3\xb2\xa1": ("<", 1_000_000, "microsecond"),
    b"\x4d\x3c\xb2\xa1": ("<", 1_000_000_000, "nanosecond"),
    b"\xa1\xb2\xc3\xd4": (">", 1_000_000, "microsecond"),
    b"\xa1\xb2\x3c\x4d": (">", 1_000_000_000, "nanosecond"),
}
LINK_TYPES = {1: "Ethernet", 127: "IEEE 802.11 with radiotap"}
MGMT_SUBTYPES = {
    0: "Association request", 1: "Association response", 2: "Reassociation request",
    3: "Reassociation response", 4: "Probe request", 5: "Probe response",
    8: "Beacon", 9: "ATIM", 10: "Disassociation", 11: "Authentication",
    12: "Deauthentication", 13: "Action", 14: "Action no-ack",
}
CONTROL_SUBTYPES = {
    7: "Control wrapper", 8: "Block ACK request", 9: "Block ACK", 10: "PS-Poll",
    11: "RTS", 12: "CTS", 13: "ACK", 14: "CF-End", 15: "CF-End + CF-Ack",
}
DATA_SUBTYPES = {
    0: "Data", 1: "Data + CF-Ack", 2: "Data + CF-Poll", 3: "Data + CF-Ack + CF-Poll",
    4: "Null", 5: "CF-Ack", 6: "CF-Poll", 7: "CF-Ack + CF-Poll",
    8: "QoS data", 9: "QoS data + CF-Ack", 10: "QoS data + CF-Poll",
    11: "QoS data + CF-Ack + CF-Poll", 12: "QoS null", 14: "QoS CF-Poll",
    15: "QoS CF-Ack + CF-Poll",
}
SCENARIO_NOTES = {
    "_root": "Initial two-Switch capture. The recorded traffic is mainly infrastructure Wi-Fi; the project notes found no Nintendo LDN room in this file, so retain it as a negative control.",
    "discovery_20260824_081253": "Native Switch-to-Switch FRLG discovery and trade flow captured while both radios hopped channels 1-13. It proves discovery and radio reception, but hopping gaps make it unsuitable as a lossless replay.",
    "guest_8188_vblank_movement_live_20260824_224736": "RTL8188EU guest-side VBlank and movement experiment. This is diagnostic evidence from the guest compatibility investigation, not a production compatibility certificate.",
    "guest_8188_vm_vblank_movement_live_20260824_232128": "Two-VM RTL8188EU guest/observer experiment covering scan, association attempts, guarded join, and movement timing. Preserve as diagnostic and negative-path evidence.",
    "native_fixed_handshake_20260824_live": "Fixed-channel native Switch handshake, room entry, idle traffic, and exit captured on two radios. Strong native protocol reference; project notes do not claim a completed Pokémon offer/confirm in this set.",
    "pc_host_20260824_085514": "PC-host discovery and join gate. A real Switch saw and joined the CODEX room; the next missing boundary was Pia session initiation.",
    "pc_host_pia_acquire_20260824_125729": "Early PC-host Pia acquisition experiment used to locate the first decrypted session boundary.",
    "pc_host_pia_srcid_20260824_130809": "PC-host Pia source-ID diagnostic used to validate peer/source identity handling.",
    "pc_host_pia_smoke_20260824_135929": "Short PC-host Pia smoke capture used to confirm the acquisition path before longer live runs.",
    "pc_host_bridge_diag_20260824_141144": "Bridge/AP/TAP/monitor diagnostic comparing encrypted over-air traffic with host-side network interfaces.",
    "pc_host_ccmp_fix_validation_20260824_142005": "CCMP fix validation captured from multiple host vantage points; preserve as a before/after diagnostic rather than an end-to-end trade proof.",
    "pc_host_ccmp_fix_live_20260824_144343": "Live CCMP boundary validation showing the PC-host ARP/Pia boundary and Reliable initialization behavior.",
    "pc_host_parent_wa_live_20260824_151803": "PC-parent Reliable WA bootstrap experiment.",
    "pc_host_parent_ni_live_20260824_154857": "PC-parent bidirectional NI/bootstrap experiment with monitor-side packet logs.",
    "pc_host_parent_uni_live_20260824_162720": "PC-parent UNI room-entry experiment used to advance the live protocol boundary.",
    "pc_host_parent_standby_live_20260824_165140": "PC-parent standby-order experiment used to isolate the next leader-state boundary.",
    "pc_host_parent_fast_recovery_live_20260824_171500": "PC-parent recovery experiment after a transient Reliable/room-entry failure.",
    "pc_host_parent_reflection_fifo_live_20260824_175304": "Reflection FIFO run that isolated a deterministic leader standby-order deadlock; lower radio and Pia layers remained healthy.",
    "pc_host_post_seat_standby_live_20260824_181522": "Hardware pass for ordered post-seat standby counts 2 and 3; the next missing layer was parent party exchange.",
    "pc_host_parent_party_pulls_live_20260824_183308": "Hardware pass for all five parent party-data pulls and visible entry into the Pokémon trade menu.",
    "pc_host_leader_selection_live_20260824_185906": "Early leader-selection live attempt retained as an intermediate/diagnostic sample.",
    "pc_host_leader_selection_live_20260824_190259": "Leader-selection retry retained as an intermediate/diagnostic sample.",
    "pc_host_leader_selection_live_20260824_190447": "Hardware pass for player-zero selection and the visible confirmation screen.",
    "pc_host_start_trade_live_20260824_191729": "Hardware pass for player-zero START_TRADE, scene transition, and the full trade animation up to READY_FINISH_TRADE.",
    "pc_host_confirm_finish_live_20260824_194059": "Hardware pass for CONFIRM_FINISH_TRADE and persistence; a later extra save count caused a return-path deadlock.",
    "pc_host_reactive_save_live_20260824_195450": "Hardware pass for Switch-driven save barriers 5-10; the next missing boundary was parent menu re-entry.",
    "pc_host_parent_reentry_live_20260824_200611": "Hardware pass for post-save party reconstruction and menu re-entry; final cancel was sent too early.",
    "pc_host_final_close_live_20260824_204047": "Trade, save, menu return, cancel, and counts 11/12 passed; room-exit one-shots were split across frames.",
    "pc_host_atomic_exit_live_20260824_205259": "Negative entry sample: native error 2318-0013 occurred before the atomic-exit code under test could run.",
    "pc_host_atomic_exit_retry_live_20260824_210720": "Negative animation sample: the session reached START_TRADE but failed before READY_FINISH_TRADE and commit.",
    "pc_host_atomic_exit_switcha_retry_live_20260824_212450": "Complete successful FRLG trade and atomic game-level room exit. A native popup occurred only after game protocol closure and did not roll back the trade.",
    "wsl_8188_controlled_20260825": "Controlled RTL8188EU guest/observer and channel-jitter experiments. Use for driver/control-port diagnosis, not as proof of production guest compatibility.",
    "wsl": "WSL radio validation captures: channel RX, external injection, frame-type coverage, and soak/stability evidence. These prove measured radio behavior, not complete Nintendo guest compatibility.",
}
FILE_NOTES = {
    "golden_backup.pcap": "Initial 28-minute baseline: 44,807 frames and no Nintendo LDN advertisement/authentication according to the original deep analysis.",
    "rtl8188eu_allch.pcap": "Secondary RTL8188EU channel-hopping view of the native discovery/trade session; use with the RTL8192EU view to corroborate radio visibility, not to reconstruct every packet.",
    "rtl8192eu_allch.pcap": "Primary RTL8192EU channel-hopping view used to identify native CH11 and CH1 LDN rooms and the joining peer.",
    "g3-8192eu-ch1.pcap": "Five-second RTL8192EU receive-health sample on channel 1; the experiment recorded 109 frames and zero kernel drops.",
    "g3-8192eu-ch6.pcap": "Five-second RTL8192EU receive-health sample on channel 6; the experiment recorded 53 frames and zero kernel drops.",
    "g3-8192eu-ch11.pcap": "Five-second RTL8192EU receive-health sample on channel 11; the experiment recorded 3 frames and zero kernel drops.",
    "g4-8192eu-self.pcap": "Same-radio injection/self-capture experiment. Injection calls succeeded, but absence of a same-radio echo means this file is not external RF-transmission proof.",
    "g4-wsl8192-to-vm8188.pcap": "External RTL8188EU observer view of a fast 100-marker RTL8192EU injection test; 42 markers were captured and were byte-exact after radiotap removal.",
    "g4-wsl8192-to-vm8188-10hz.pcap": "External 10 Hz injection sample: 28 of 30 unique markers were captured, with no duplicates and byte-exact 802.11 content.",
    "g4-wsl8192-to-vm8188-10hz-100.pcap": "External 10 Hz injection sample: 90 of 100 unique markers were captured, with no duplicates and byte-exact 802.11 content.",
    "soak-8188-patched-5m.pcap": "Five-minute patched RTL8188EU receive soak: 8,474 captured packets, 8,476 received by filter, and zero kernel drops in the original test report.",
    "soak-wsl-8192-final.pcap": "Final 30-minute WSL RTL8192EU receive soak: 41,394 packets and zero kernel drops in the original test report.",
    "vendor8188-frame-types.pcap": "External frame-type coverage for patched RTL8188EU injection: probe 24/25, vendor action 24/25, beacon 25/25, and data 25/25 in the original analysis.",
    "vendor8188-g4-rx.pcap": "External RTL8188EU receive view of RTL8192EU injection: 86/100 unique frames with exact addresses/payload and receiver-added FCS.",
    "vendor8188-g4-tx.pcap": "External RTL8192EU receive view of RTL8188EU injection: 98/100 unique frames; sequence control changed as expected while addresses/payload remained exact.",
    "host_ap_netdev.pcap": "Empty AP-netdev capture retained because the absence of packets helped compare AP, monitor, and TAP visibility during bridge diagnosis.",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mac(raw: bytes) -> str:
    return ":".join(f"{byte:02x}" for byte in raw) if len(raw) == 6 else ""


def format_time(epoch: float | None, zone: ZoneInfo = KST) -> str:
    if epoch is None:
        return "n/a"
    return datetime.fromtimestamp(epoch, timezone.utc).astimezone(zone).isoformat(timespec="microseconds")


def align(offset: int, boundary: int) -> int:
    return (offset + boundary - 1) & ~(boundary - 1)


def radiotap_info(packet: bytes) -> tuple[int, int | None, bool | None]:
    if len(packet) < 8 or packet[0] != 0:
        return 0, None, None
    length = struct.unpack_from("<H", packet, 2)[0]
    if length < 8 or length > len(packet):
        return 0, None, None
    words, offset = [], 4
    while offset + 4 <= length:
        word = struct.unpack_from("<I", packet, offset)[0]
        words.append(word)
        offset += 4
        if not (word & 0x80000000):
            break
    field_offset = offset
    flags, frequency = None, None
    fields = {0: (8, 8), 1: (1, 1), 2: (1, 1), 3: (2, 4)}
    present = words[0] if words else 0
    for bit in range(4):
        if present & (1 << bit):
            field_align, field_size = fields[bit]
            field_offset = align(field_offset, field_align)
            if field_offset + field_size > length:
                break
            if bit == 1:
                flags = packet[field_offset]
            elif bit == 3:
                frequency = struct.unpack_from("<H", packet, field_offset)[0]
            field_offset += field_size
    return length, frequency, bool(flags & 0x10) if flags is not None else None


def channel_from_frequency(frequency: int) -> str:
    if frequency == 2484:
        return "2.4 GHz ch 14"
    if 2412 <= frequency <= 2472:
        return f"2.4 GHz ch {(frequency - 2407) // 5}"
    if 5000 <= frequency <= 5900:
        return f"5 GHz ch {(frequency - 5000) // 5}"
    return f"{frequency} MHz"


def parse_wifi(frame: bytes, stats: dict) -> None:
    if len(frame) < 2:
        stats["malformed_frames"] += 1
        return
    fc = struct.unpack_from("<H", frame, 0)[0]
    frame_type, subtype = (fc >> 2) & 0x3, (fc >> 4) & 0xF
    flags = (fc >> 8) & 0xFF
    type_name = {0: "Management", 1: "Control", 2: "Data", 3: "Extension"}.get(frame_type, "Unknown")
    subtype_name = ({0: MGMT_SUBTYPES, 1: CONTROL_SUBTYPES, 2: DATA_SUBTYPES}.get(frame_type, {})).get(subtype, f"Subtype {subtype}")
    stats["frame_types"][type_name] += 1
    stats["frame_subtypes"][f"{type_name}: {subtype_name}"] += 1
    if flags & 0x08:
        stats["retry_frames"] += 1
    if frame_type == 2 and flags & 0x40:
        stats["protected_data_frames"] += 1
    if frame_type == 2 and not (flags & 0x40):
        stats["unprotected_data_frames"] += 1
    if frame_type == 0 and subtype == 13 and len(frame) > 24 and frame[24] == 127:
        stats["vendor_specific_actions"] += 1
    addr1 = mac(frame[4:10]) if len(frame) >= 10 else ""
    addr2 = mac(frame[10:16]) if len(frame) >= 16 else ""
    addr3 = mac(frame[16:22]) if len(frame) >= 22 else ""
    source = destination = bssid = ""
    if frame_type == 0:
        destination, source, bssid = addr1, addr2, addr3
    elif frame_type == 1:
        destination, source = addr1, addr2
    elif frame_type == 2:
        to_ds, from_ds = bool(flags & 0x01), bool(flags & 0x02)
        if not to_ds and not from_ds:
            destination, source, bssid = addr1, addr2, addr3
        elif to_ds and not from_ds:
            bssid, source, destination = addr1, addr2, addr3
        elif not to_ds and from_ds:
            destination, bssid, source = addr1, addr2, addr3
        elif len(frame) >= 30:
            destination, source = addr3, mac(frame[24:30])
    for value, key in ((source, "sources"), (destination, "destinations"), (bssid, "bssids")):
        if value:
            stats[key][value] += 1


def parse_ethernet(frame: bytes, stats: dict) -> None:
    if len(frame) < 14:
        stats["malformed_frames"] += 1
        return
    destination, source = mac(frame[0:6]), mac(frame[6:12])
    stats["sources"][source] += 1
    stats["destinations"][destination] += 1
    ethertype, offset = struct.unpack_from("!H", frame, 12)[0], 14
    if ethertype in (0x8100, 0x88A8) and len(frame) >= 18:
        ethertype, offset = struct.unpack_from("!H", frame, 16)[0], 18
    ethertype_name = {0x0800: "IPv4", 0x0806: "ARP", 0x86DD: "IPv6"}.get(ethertype, f"0x{ethertype:04x}")
    stats["ethertypes"][ethertype_name] += 1
    if ethertype != 0x0800 or len(frame) < offset + 20:
        return
    version_ihl = frame[offset]
    ihl = (version_ihl & 0x0F) * 4
    if version_ihl >> 4 != 4 or ihl < 20 or len(frame) < offset + ihl:
        stats["malformed_frames"] += 1
        return
    protocol = frame[offset + 9]
    source_ip = socket.inet_ntoa(frame[offset + 12:offset + 16])
    destination_ip = socket.inet_ntoa(frame[offset + 16:offset + 20])
    stats["ip_sources"][source_ip] += 1
    stats["ip_destinations"][destination_ip] += 1
    protocol_name = {1: "ICMP", 6: "TCP", 17: "UDP"}.get(protocol, str(protocol))
    stats["ip_protocols"][protocol_name] += 1
    transport = offset + ihl
    if protocol in (6, 17) and len(frame) >= transport + 4:
        source_port, destination_port = struct.unpack_from("!HH", frame, transport)
        stats["ports"][f"{protocol_name} {source_port}"] += 1
        stats["ports"][f"{protocol_name} {destination_port}"] += 1


def pcap_stats(path: Path) -> dict:
    result = {
        "format": "classic pcap", "timestamp_resolution": None, "link_type": None,
        "link_type_name": None, "snaplen": None, "packets": 0, "captured_bytes": 0,
        "original_bytes": 0, "truncated_packets": 0, "first_epoch": None, "last_epoch": None,
        "malformed_frames": 0, "parse_warnings": [], "frame_types": Counter(),
        "frame_subtypes": Counter(), "sources": Counter(), "destinations": Counter(),
        "bssids": Counter(), "frequencies": Counter(), "fcs_flag": Counter(),
        "protected_data_frames": 0, "unprotected_data_frames": 0, "retry_frames": 0,
        "vendor_specific_actions": 0, "ethertypes": Counter(), "ip_protocols": Counter(),
        "ip_sources": Counter(), "ip_destinations": Counter(), "ports": Counter(),
    }
    with path.open("rb") as stream:
        header = stream.read(24)
        if len(header) != 24 or header[:4] not in PCAP_MAGICS:
            raise ValueError("not a supported classic pcap")
        endian, scale, resolution = PCAP_MAGICS[header[:4]]
        _, _, _, _, snaplen, network = struct.unpack(endian + "HHIIII", header[4:])
        link_type = network & 0xFFFF
        result.update(timestamp_resolution=resolution, link_type=link_type,
                      link_type_name=LINK_TYPES.get(link_type, f"DLT {link_type}"), snaplen=snaplen)
        while True:
            packet_header = stream.read(16)
            if not packet_header:
                break
            if len(packet_header) != 16:
                result["parse_warnings"].append("truncated packet header at end of file")
                break
            seconds, fraction, captured, original = struct.unpack(endian + "IIII", packet_header)
            packet = stream.read(captured)
            if len(packet) != captured:
                result["parse_warnings"].append("truncated packet data at end of file")
                break
            epoch = seconds + fraction / scale
            result["first_epoch"] = epoch if result["first_epoch"] is None else result["first_epoch"]
            result["last_epoch"] = epoch
            result["packets"] += 1
            result["captured_bytes"] += captured
            result["original_bytes"] += original
            result["truncated_packets"] += int(captured < original)
            if link_type == 127:
                radio_length, frequency, fcs = radiotap_info(packet)
                if not radio_length:
                    result["malformed_frames"] += 1
                    continue
                if frequency:
                    result["frequencies"][channel_from_frequency(frequency)] += 1
                result["fcs_flag"]["present" if fcs else "absent" if fcs is False else "unknown"] += 1
                frame = packet[radio_length:]
                if fcs and len(frame) >= 4:
                    frame = frame[:-4]
                parse_wifi(frame, result)
            elif link_type == 1:
                parse_ethernet(packet, result)
        if result["first_epoch"] is not None:
            result["duration_seconds"] = max(0.0, result["last_epoch"] - result["first_epoch"])
            result["average_packets_per_second"] = result["packets"] / result["duration_seconds"] if result["duration_seconds"] else None
        else:
            result["duration_seconds"] = 0.0
            result["average_packets_per_second"] = None
    for key, value in list(result.items()):
        if isinstance(value, Counter):
            result[key] = dict(value.most_common())
    return result


def first_heading(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def scenario_for(relative: Path, source_group: str) -> tuple[str, str, str]:
    if source_group == "wsl":
        return "WSL radio validation", "hardware-validation", SCENARIO_NOTES["wsl"]
    folder = relative.parts[0] if len(relative.parts) > 1 else "_root"
    source_dir = Path("logs/golden") / (folder if folder != "_root" else "")
    local_doc = next((source_dir / name for name in ("MANIFEST.md", "README.md") if (source_dir / name).exists()), None)
    title = first_heading(local_doc) if local_doc else None
    if not title:
        title = "Initial golden capture" if folder == "_root" else folder.replace("_", " ")
    title_lower = title.lower()
    if folder == "_root":
        status = "negative-control"
    elif "full trade" in title_lower or "atomic room-exit proof" in title_lower:
        status = "full-pass"
    elif "negative" in title_lower:
        status = "negative-control"
    elif "pass" in title_lower:
        status = "boundary-pass"
    elif folder in ("discovery_20260824_081253", "native_fixed_handshake_20260824_live"):
        status = "native-reference"
    else:
        status = "diagnostic"
    return title, status, SCENARIO_NOTES.get(folder, f"Capture from the {title} experiment. Treat conclusions as limited to the measured vantage point and captured interval.")


def vantage(filename: str) -> str:
    name = filename.lower()
    if "observer" in name:
        return "Independent over-air observer radio"
    if "ldn_tap" in name:
        return "PC-host LDN TAP (decrypted Ethernet-side traffic)"
    if "ap_netdev" in name:
        return "PC-host AP network interface"
    if "ldn_mon" in name:
        return "PC-host monitor interface (over-air 802.11)"
    if "rtl8192" in name or "8192" in name:
        return "RTL8192EU radio capture"
    if "rtl8188" in name or "8188" in name:
        return "RTL8188EU radio capture"
    if "pia" in name:
        return "Pia application/session stream"
    if "startup" in name:
        return "Startup interval capture"
    if "session" in name:
        return "Session interval capture"
    return "Capture vantage identified by the enclosing scenario and filename"


def limitation(relative: Path, stats: dict, status: str) -> str:
    parts = relative.as_posix().lower()
    notes = []
    if stats["link_type"] == 127:
        notes.append("Over-air 802.11 payloads may be encrypted; this inventory does not decrypt them.")
    elif stats["link_type"] == 1:
        notes.append("Ethernet/TAP capture omits 802.11 management, radiotap, RSSI, and channel details.")
    if "allch" in parts or "discovery_" in parts:
        notes.append("Channel hopping creates intentional gaps and prevents lossless stream reconstruction.")
    if status in ("negative-control", "diagnostic"):
        notes.append("This is diagnostic/negative-path evidence and must not be cited as an end-to-end success.")
    if "observer" in parts:
        notes.append("An observer capture can include unrelated nearby traffic and cannot alone prove host-side decryption or application state.")
    return " ".join(notes) or "Interpret only within the documented scenario and capture interval."


def top_rows(mapping: dict, limit: int = 8) -> list[tuple[str, int]]:
    return list(mapping.items())[:limit]


def md_table(rows: list[tuple], headers: tuple[str, ...]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |" for row in rows)
    return "\n".join(lines)


def write_capture_analysis(path: Path, capture: dict, bundle: Path) -> None:
    stats = capture["analysis"]
    capture_link = Path(os.path.relpath(bundle / capture["bundle_path"], path.parent)).as_posix()
    source_links = []
    for note in capture["source_notes"]:
        target = Path(os.path.relpath(bundle / "documentation/source-notes" / note, path.parent)).as_posix()
        source_links.append(f"[{note}]({target})")
    for local_doc in capture["capture_local_docs"]:
        target = Path(os.path.relpath(bundle / local_doc, path.parent)).as_posix()
        source_links.insert(0, f"[{Path(local_doc).name}]({target})")
    lines = [
        f"# {capture['id']} — {capture['scenario_title']}", "",
        f"**Label:** `{capture['status']}` · **Vantage:** {capture['vantage']}", "",
        capture["file_summary"], "", capture["scenario_summary"], "",
        "## Identity and provenance", "",
        md_table([
            ("Original path", f"`{capture['source_path']}`"),
            ("Bundled capture", f"[{capture['bundle_path']}]({capture_link})"),
            ("SHA-256", f"`{capture['sha256']}`"),
            ("Size", f"{capture['size_bytes']:,} bytes"),
            ("Format", f"{stats['format']}; {stats['link_type_name']} (DLT {stats['link_type']})"),
        ], ("Field", "Value")), "",
        "## Measured capture profile", "",
        md_table([
            ("Packets", f"{stats['packets']:,}"),
            ("Captured bytes", f"{stats['captured_bytes']:,}"),
            ("Start (Asia/Seoul)", format_time(stats['first_epoch'])),
            ("End (Asia/Seoul)", format_time(stats['last_epoch'])),
            ("Duration", f"{stats['duration_seconds']:.6f} s"),
            ("Average rate", f"{stats['average_packets_per_second']:.3f} packets/s" if stats['average_packets_per_second'] is not None else "n/a"),
            ("Truncated packets", f"{stats['truncated_packets']:,}"),
            ("Malformed/short frames", f"{stats['malformed_frames']:,}"),
        ], ("Metric", "Value")), "",
    ]
    if stats["link_type"] == 127:
        lines.extend([
            "## 802.11 analysis", "",
            md_table(top_rows(stats["frame_subtypes"], 16), ("Frame class", "Count")), "",
            md_table([
                ("Protected data frames", f"{stats['protected_data_frames']:,}"),
                ("Unprotected data frames", f"{stats['unprotected_data_frames']:,}"),
                ("Retry-flagged frames", f"{stats['retry_frames']:,}"),
                ("Vendor-specific action frames (category 127)", f"{stats['vendor_specific_actions']:,}"),
            ], ("Signal", "Count")), "",
            "### Observed channels", "",
            md_table(top_rows(stats["frequencies"]), ("Channel/frequency", "Packets")) if stats["frequencies"] else "No channel field was decoded from radiotap.", "",
            "### Top BSSIDs", "",
            md_table(top_rows(stats["bssids"]), ("BSSID", "Frames")) if stats["bssids"] else "No BSSID was derivable from decoded headers.", "",
            "### Top source addresses", "",
            md_table(top_rows(stats["sources"]), ("Source", "Frames")) if stats["sources"] else "No source address was derivable.", "",
        ])
    elif stats["link_type"] == 1:
        lines.extend([
            "## Ethernet/TAP analysis", "",
            md_table(top_rows(stats["ethertypes"]), ("EtherType", "Frames")), "",
            "### IP protocols", "",
            md_table(top_rows(stats["ip_protocols"]), ("Protocol", "Frames")) if stats["ip_protocols"] else "No IPv4 protocol records decoded.", "",
            "### Top IP sources", "",
            md_table(top_rows(stats["ip_sources"]), ("Source IP", "Packets")) if stats["ip_sources"] else "No IPv4 source addresses decoded.", "",
            "### Top transport ports", "",
            md_table(top_rows(stats["ports"]), ("Protocol/port", "Occurrences")) if stats["ports"] else "No TCP/UDP ports decoded.", "",
        ])
    lines.extend([
        "## Interpretation", "",
        f"This file records the **{capture['vantage'].lower()}** for the scenario above. {capture['file_summary']}", "",
        "## Limits", "", capture["limitations"], "",
        "## Related documentation", "",
        ", ".join(source_links) if source_links else "No exact source-note reference was found; use the scenario label, measured profile, and sibling files together.", "",
        "## AI handoff", "",
        "Use the matching object in `catalog.json` for structured metrics. Do not infer decrypted Nintendo/Pia semantics from frame counts alone; pair this page with the listed source notes and sibling capture vantage points.", "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def jsonl_stats(path: Path) -> dict:
    stats = {"lines": 0, "valid_json": 0, "invalid_json": 0, "records": Counter(), "directions": Counter(), "protocols": Counter(), "declared_payload_bytes": 0}
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            stats["lines"] += 1
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                stats["invalid_json"] += 1
                continue
            stats["valid_json"] += 1
            stats["records"][str(item.get("rec", "unknown"))] += 1
            if "dir" in item:
                stats["directions"][str(item["dir"])] += 1
            if "proto" in item:
                stats["protocols"][str(item["proto"])] += 1
            if isinstance(item.get("len"), int):
                stats["declared_payload_bytes"] += item["len"]
    for key in ("records", "directions", "protocols"):
        stats[key] = dict(stats[key].most_common())
    return stats


def text_stats(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    lowered = text.lower()
    lines = text.splitlines()
    return {
        "lines": len(lines), "nonempty_lines": sum(bool(line.strip()) for line in lines),
        "error_mentions": lowered.count("error"), "failure_mentions": lowered.count("fail"),
        "warning_mentions": lowered.count("warning"), "pass_mentions": lowered.count("pass"),
    }


def json_stats(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as error:
        return {"valid_json": False, "error": str(error)}
    if isinstance(data, dict):
        result = {"valid_json": True, "top_level_type": "object", "top_level_keys": list(data)[:30]}
        for key in ("overall_status", "run_id", "contract_version"):
            if key in data:
                result[key] = data[key]
        return result
    return {"valid_json": True, "top_level_type": type(data).__name__, "items": len(data) if isinstance(data, list) else None}


def png_dimensions(path: Path) -> tuple[int | None, int | None]:
    with path.open("rb") as stream:
        head = stream.read(24)
    if len(head) == 24 and head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
        return struct.unpack(">II", head[16:24])
    return None, None


def description_for(path: Path, category: str) -> str:
    name = path.name.lower()
    if path.suffix.lower() == ".pcap":
        return vantage(path.name)
    if name in ("manifest.md", "readme.md"):
        return "Capture-local scenario documentation and provenance."
    if name.endswith("pia.jsonl") or name == "host_pia.jsonl":
        return "Structured Pia packet stream with direction, endpoints, lengths, and raw payload hex."
    if name == "events.jsonl":
        return "Structured hardware-diagnostic event stream."
    if name == "diagnostic-report.json":
        return "Machine-readable hardware diagnostic verdict and per-stage results."
    if name == "metadata.json":
        return "Run identity, application commit, platform, adapter, mode, and role metadata."
    if name.startswith("diagnostic-"):
        return "Raw diagnostic evidence for the subsystem named in the filename."
    if path.suffix.lower() == ".log":
        return "Console or packet-tool log retained for timeline and failure analysis."
    if path.suffix.lower() == ".pk3":
        return "Captured 100-byte Pokémon payload; useful for decoder validation and potentially personally identifying game data."
    if path.suffix.lower() in (".sh", ".py"):
        return "Exact experiment runner or diagnostic helper retained for reproducibility."
    if path.suffix.lower() == ".json":
        return "Machine-readable decoder or diagnostic output."
    if path.suffix.lower() == ".txt":
        return "Text evidence, checksum record, or diagnostic output."
    if path.suffix.lower() == ".png":
        return f"UI/reference screenshot labeled from `{path.stem}`."
    return f"Companion evidence file for the {category} collection."


def sensitivity_for(path: Path) -> str:
    if path.suffix.lower() in (".pcap", ".jsonl", ".pk3", ".log"):
        return "restricted-test-data"
    return "developer-internal"


def related_source_notes(repo: Path, relative: Path, group: str, markdown: list[Path]) -> list[str]:
    primary = relative.parent.name if relative.parent.name else relative.name
    matches = [note.relative_to(repo).as_posix() for note in markdown if primary in note.read_text(encoding="utf-8", errors="replace")]
    if not matches:
        matches = [note.relative_to(repo).as_posix() for note in markdown if relative.name in note.read_text(encoding="utf-8", errors="replace")]
    if group == "wsl" and not matches:
        matches = ["docs/24-wsl-radio-validation-20260824.md", "handoff/HANDOFF-20260823-wsl-transition.md"]
    return matches


def copy_tree_files(source: Path, destination: Path) -> list[tuple[Path, Path]]:
    copied = []
    for item in sorted(path for path in source.rglob("*") if path.is_file()):
        target = destination / item.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        copied.append((item, target))
    return copied


def build(repo: Path, bundle: Path, update: bool = False) -> None:
    if bundle.exists() and not update:
        raise SystemExit(f"Refusing to overwrite existing output: {bundle}")
    bundle.mkdir(parents=True, exist_ok=update)
    source_markdown = sorted(list((repo / "docs").glob("*.md")) + list((repo / "handoff").glob("*.md")))
    evidence, captures = [], []

    copy_sets = [
        (repo / "logs/golden", bundle / "evidence/network/golden", "network-golden"),
        (repo / "logs/wsl", bundle / "evidence/network/wsl", "network-wsl"),
        (repo / "artifacts/qa/hardware-current", bundle / "evidence/hardware-diagnostics", "hardware-diagnostic"),
    ]
    artifact_pngs = sorted(
        path for path in (repo / "artifacts").rglob("*.png")
        if not any(parent.name.startswith("SwitchTrade-capture-evidence-") for parent in path.parents)
    )
    for source, destination, category in copy_sets:
        for original, copied in copy_tree_files(source, destination):
            relative_source = original.relative_to(repo).as_posix()
            entry = {
                "source_path": relative_source,
                "bundle_path": copied.relative_to(bundle).as_posix(),
                "category": category,
                "kind": original.suffix.lower().lstrip(".") or "file",
                "size_bytes": original.stat().st_size,
                "sha256": sha256(original),
                "description": description_for(original, category),
                "sensitivity": sensitivity_for(original),
            }
            if original.suffix.lower() == ".jsonl":
                entry["content_summary"] = jsonl_stats(original)
            elif original.suffix.lower() in (".log", ".txt", ".md", ".sh", ".py"):
                entry["content_summary"] = text_stats(original)
            elif original.suffix.lower() == ".json":
                entry["content_summary"] = json_stats(original)
            evidence.append(entry)
    for original in artifact_pngs:
        relative = original.relative_to(repo / "artifacts")
        copied = bundle / "evidence/ui" / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, copied)
        width, height = png_dimensions(original)
        evidence.append({
            "source_path": original.relative_to(repo).as_posix(),
            "bundle_path": copied.relative_to(bundle).as_posix(),
            "category": "ui-capture", "kind": "png", "size_bytes": original.stat().st_size,
            "sha256": sha256(original), "description": description_for(original, "ui-capture"),
            "sensitivity": "developer-internal", "image_width": width, "image_height": height,
        })

    relevant_notes = set()
    pcap_entries = [entry for entry in evidence if entry["kind"] == "pcap"]
    for index, entry in enumerate(pcap_entries, 1):
        original = repo / entry["source_path"]
        if entry["source_path"].startswith("logs/golden/"):
            group = "golden"
            relative = original.relative_to(repo / "logs/golden")
        else:
            group = "wsl"
            relative = original.relative_to(repo / "logs/wsl")
        title, status, summary = scenario_for(relative, group)
        stats = pcap_stats(original)
        notes = related_source_notes(repo, relative, group, source_markdown)
        relevant_notes.update(notes)
        local_docs = []
        for name in ("MANIFEST.md", "README.md"):
            candidate = original.parent / name
            if candidate.exists():
                source_entry = next(item for item in evidence if item["source_path"] == candidate.relative_to(repo).as_posix())
                local_docs.append(source_entry["bundle_path"])
        capture_id = f"CAP-{index:03d}"
        analysis_path = Path("analysis/network") / group / relative.parent / f"{relative.name}.md"
        capture = {
            "id": capture_id, "source_path": entry["source_path"], "bundle_path": entry["bundle_path"],
            "analysis_path": analysis_path.as_posix(), "size_bytes": entry["size_bytes"],
            "sha256": entry["sha256"], "scenario_title": title, "status": status,
            "scenario_summary": summary, "vantage": vantage(relative.name),
            "file_summary": FILE_NOTES.get(relative.name, f"This file is the {vantage(relative.name).lower()} for this scenario; the measured profile below distinguishes it from sibling vantage points."),
            "limitations": limitation(relative, stats, status), "source_notes": notes,
            "capture_local_docs": local_docs,
            "analysis": stats,
        }
        captures.append(capture)
        entry["capture_id"] = capture_id
        print(f"Analyzed {capture_id} {entry['source_path']} ({stats['packets']:,} packets)", flush=True)

    relevant_notes.update({
        "docs/22-golden-capture-playbook.md", "docs/23-goldencapture-1차결과.md",
        "docs/24-wsl-radio-validation-20260824.md", "docs/25-goldencapture-2차-WSL-결과.md",
        "docs/27-golden-capture-reverse-engineering-plan.md", "handoff/HANDOFF-20260823-goldencapture.md",
        "handoff/HANDOFF-20260823-wsl-transition.md",
    })
    for relative in sorted(relevant_notes):
        source = repo / relative
        if source.exists():
            target = bundle / "documentation/source-notes" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    for capture in captures:
        write_capture_analysis(bundle / capture["analysis_path"], capture, bundle)

    generated = datetime.now(timezone.utc).isoformat()
    catalog = {
        "schema_version": "switchtrade.capture-catalog.v1", "generated_utc": generated,
        "bundle_name": bundle.name, "capture_count": len(captures),
        "labels": {
            "full-pass": "End-to-end target transaction passed; read limitations for post-close caveats.",
            "boundary-pass": "The documented protocol boundary passed; later stages may still fail.",
            "native-reference": "Native Switch behavior retained as a protocol reference.",
            "hardware-validation": "Radio/driver behavior was measured; not an end-to-end product claim.",
            "negative-control": "Known failure or absence retained to distinguish incorrect hypotheses.",
            "diagnostic": "Intermediate evidence useful for narrowing a fault; not a success claim.",
        },
        "captures": captures,
    }
    (bundle / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (bundle / "evidence-files.json").write_text(json.dumps({"schema_version": "switchtrade.evidence-files.v1", "generated_utc": generated, "files": evidence}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    catalog_rows = []
    for capture in captures:
        stats = capture["analysis"]
        catalog_rows.append((
            capture["id"], capture["status"], capture["scenario_title"], capture["vantage"],
            f"{stats['packets']:,}", f"{stats['duration_seconds']:.3f}s",
            f"[{Path(capture['source_path']).name}]({capture['bundle_path']})",
            f"[analysis]({capture['analysis_path']})",
        ))
    (bundle / "CATALOG.md").write_text("# Packet-capture catalog\n\n" + md_table(catalog_rows, ("ID", "Label", "Scenario", "Vantage", "Packets", "Duration", "Capture", "Analysis")) + "\n", encoding="utf-8")

    companion_rows = []
    for entry in evidence:
        if entry["kind"] == "pcap" or entry["category"] in ("hardware-diagnostic", "ui-capture"):
            continue
        summary = entry.get("content_summary")
        detail = entry["description"]
        if summary:
            if entry["kind"] == "jsonl":
                detail += f" Lines: {summary['lines']:,}; records: {summary['records']}; directions: {summary['directions']}."
            elif "lines" in summary:
                detail += f" Lines: {summary['lines']:,}; error/fail/warning/PASS mentions: {summary['error_mentions']}/{summary['failure_mentions']}/{summary['warning_mentions']}/{summary['pass_mentions']}."
            elif summary.get("valid_json"):
                detail += f" Valid JSON; top-level keys: {', '.join(summary.get('top_level_keys', []))}."
        companion_rows.append((entry["category"], f"[{entry['source_path']}]({entry['bundle_path']})", entry["size_bytes"], entry["sensitivity"], detail))
    (bundle / "COMPANION_FILES.md").write_text("# Companion evidence files\n\nThese logs, Pia streams, payloads, manifests, and runners provide application-level context for the PCAPs.\n\n" + md_table(companion_rows, ("Collection", "File", "Bytes", "Sensitivity", "Description")) + "\n", encoding="utf-8")

    hardware_rows = []
    hardware_root = repo / "artifacts/qa/hardware-current"
    for run in sorted(path for path in hardware_root.iterdir() if path.is_dir()):
        metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
        report = json.loads((run / "diagnostic-report.json").read_text(encoding="utf-8"))
        failed = ", ".join(stage["code"] for stage in report["stages"] if stage["status"] == "failed") or "none"
        warnings = ", ".join(stage["code"] for stage in report["stages"] if stage["status"] == "warning") or "none"
        link = f"evidence/hardware-diagnostics/{run.name}/diagnostic-report.json"
        hardware_rows.append((run.name, metadata["usb_id"], metadata["role"], report["overall_status"], failed, warnings, f"[report]({link})"))
    (bundle / "HARDWARE_DIAGNOSTICS.md").write_text("# Hardware diagnostic runs\n\nThese five runs preserve the exact adapter, driver, kernel, and policy states behind quick diagnostic outcomes. A failed quick diagnostic is not automatically an RF failure; inspect its stage codes and raw kernel evidence.\n\n" + md_table(hardware_rows, ("Run", "USB ID", "Role", "Status", "Failed stages", "Warnings", "Evidence")) + "\n", encoding="utf-8")

    ui_rows = []
    for entry in evidence:
        if entry["category"] == "ui-capture":
            dimensions = f"{entry['image_width']}×{entry['image_height']}" if entry["image_width"] else "unknown"
            ui_rows.append((Path(entry["source_path"]).parent.as_posix(), f"[{Path(entry['source_path']).name}]({entry['bundle_path']})", dimensions, entry["description"]))
    (bundle / "UI_CAPTURE_INDEX.md").write_text("# UI capture index\n\nScreenshots are grouped by their original artifact folder and retain their original filenames so design-history references remain stable.\n\n" + md_table(ui_rows, ("Original group", "Screenshot", "Dimensions", "Purpose label")) + "\n", encoding="utf-8")

    readme = f"""# SwitchTrade capture evidence bundle — 2026-08-27

This directory consolidates the project's locally preserved packet captures, their companion logs and payloads, WSL radio-validation captures, hardware-diagnostic runs, and UI reference screenshots. Originals were copied byte-for-byte and were not moved or edited.

## Start here

1. Read `CATALOG.md` to find a scenario and vantage point.
2. Open the linked per-capture analysis page under `analysis/network/`.
3. Read the listed source notes before making a protocol claim.
4. For automation, consume `catalog.json` and `evidence-files.json`.
5. Verify integrity with `SHA256SUMS.txt` before analysis or redistribution.

## Contents

| Path | Contents |
|---|---|
| `evidence/network/golden/` | Original golden/native/PC-host packet captures and companion evidence |
| `evidence/network/wsl/` | WSL radio RX, injection, frame-type, and soak PCAPs |
| `evidence/hardware-diagnostics/` | Five structured hardware diagnostic runs |
| `evidence/ui/` | UI/reference screenshots |
| `analysis/network/` | One measured Markdown analysis page per PCAP |
| `documentation/source-notes/` | Original project reports and handoffs relevant to these captures |
| `catalog.json` | AI-oriented packet-capture catalog and measured statistics |
| `evidence-files.json` | Machine-readable provenance and hash record for every copied evidence file |

## Inventory

- Packet captures: **{len(captures)}** ({sum(c['size_bytes'] for c in captures):,} bytes)
- Copied source evidence files: **{len(evidence)}**
- UI screenshots: **{len(ui_rows)}**
- Hardware diagnostic runs: **{len(hardware_rows)}**

## Label meanings

`full-pass` is the strongest end-to-end evidence, `boundary-pass` proves only the named stage, `native-reference` records Switch-to-Switch behavior, `hardware-validation` proves only radio/driver measurements, `negative-control` preserves known failures or absences, and `diagnostic` marks intermediate evidence.

## Analysis method

The bundle builder parses classic PCAP headers using Python's standard library. For radiotap/802.11 it reports channel fields, frame types/subtypes, retry/protected flags, category-127 vendor actions, and top MAC/BSSID values. For Ethernet/TAP captures it reports EtherTypes, IP protocols/endpoints, and transport ports. It does **not** decrypt CCMP, Nintendo advertisements, Pia, or Pokémon payloads; semantic conclusions come from the preserved source notes and capture-local manifests.

## Privacy and redistribution

This is developer evidence, not a public anonymized dataset. PCAPs and logs can contain device MAC addresses, local IPs, SSIDs/session identifiers, raw Pia payloads, trainer/Pokémon data, and nearby wireless traffic. `received.pk3` files are explicitly marked restricted test data. Cryptographic key files are not included. Do not publish the bundle publicly without a deliberate privacy review; anonymizing encrypted captures can invalidate protocol analysis.

## Important interpretation limits

- The first `golden_backup.pcap` is a negative control dominated by infrastructure Wi-Fi, not an LDN gold trace.
- Channel-hopping discovery captures prove visibility but contain intentional gaps.
- WSL/RTL8188EU injection and RX success does not prove Nintendo custom control-port guest compatibility.
- A `boundary-pass` run can end in a later deliberate stop or native error; read its manifest before citing it.
- Packet counts alone do not prove application correctness. Pair observer, host-monitor, TAP, Pia JSONL, and console evidence when available.

## Rebuilding

Run `python scripts/build-capture-evidence-bundle.py <new-output-directory>` from the repository root. The builder refuses to overwrite an existing directory unless `--update` is explicitly supplied. The copy included under `tools/` is for provenance; use the repository copy for rebuilding.
"""
    (bundle / "README.md").write_text(readme, encoding="utf-8")

    tools_dir = bundle / "tools"
    tools_dir.mkdir(exist_ok=True)
    shutil.copy2(Path(__file__), tools_dir / Path(__file__).name)

    checksum_lines = []
    for path in sorted(item for item in bundle.rglob("*") if item.is_file() and item.name != "SHA256SUMS.txt"):
        checksum_lines.append(f"{sha256(path)}  {path.relative_to(bundle).as_posix()}")
    (bundle / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    verify(bundle, expected_captures=len(pcap_entries), expected_evidence=len(evidence))
    print(f"Bundle ready: {bundle}", flush=True)


def verify(bundle: Path, expected_captures: int | None = None, expected_evidence: int | None = None) -> None:
    catalog = json.loads((bundle / "catalog.json").read_text(encoding="utf-8"))
    evidence = json.loads((bundle / "evidence-files.json").read_text(encoding="utf-8"))["files"]
    captures = catalog["captures"]
    if expected_captures is not None:
        assert len(captures) == expected_captures
    if expected_evidence is not None:
        assert len(evidence) == expected_evidence
    assert len({capture["id"] for capture in captures}) == len(captures)
    for capture in captures:
        target = bundle / capture["bundle_path"]
        assert target.is_file() and sha256(target) == capture["sha256"]
        assert (bundle / capture["analysis_path"]).is_file()
    for entry in evidence:
        target = bundle / entry["bundle_path"]
        assert target.is_file() and sha256(target) == entry["sha256"]
    checksum_file = bundle / "SHA256SUMS.txt"
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        assert sha256(bundle / relative) == expected
    print(f"Verified {len(captures)} captures, {len(evidence)} evidence files, and {len(checksum_file.read_text(encoding='utf-8').splitlines())} bundle checksums.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, nargs="?", help="new output directory")
    parser.add_argument("--verify", type=Path, help="verify an existing bundle")
    parser.add_argument("--update", action="store_true", help="refresh an existing bundle without deleting files")
    args = parser.parse_args()
    if args.verify:
        verify(args.verify.resolve())
        return
    if not args.output:
        parser.error("output is required unless --verify is used")
    repo = Path(__file__).resolve().parent.parent
    build(repo, args.output.resolve(), update=args.update)


if __name__ == "__main__":
    main()
