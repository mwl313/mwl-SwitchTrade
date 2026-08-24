#!/usr/bin/env python3
"""Extract Pokémon candidates from the emulator's encrypted Pia JSONL capture.

The protocol repository already owns Pia crypto and Reliable/GBA framing. This
small adapter reuses those implementations, then hands RFU commands to the
payload-side block assembler and Gen-III scanner. It emits decoded metadata,
never raw pcap bytes or keys.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EMU_ROOT = ROOT / "_related" / "frlg-ldn-trade-emu"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(EMU_ROOT) not in sys.path:
    sys.path.insert(0, str(EMU_ROOT))

from tools import payload_decoder


@dataclass(frozen=True)
class ExtractionStats:
    datagrams: int = 0
    decrypt_failures: int = 0
    reliable_messages: int = 0
    gba_frames: int = 0
    command_counts: dict[str, int] | None = None


def _load_jsonl(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    meta: dict[str, Any] | None = None
    packets: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON") from exc
            if row.get("rec") == "meta":
                if meta is not None:
                    raise ValueError(f"{path}:{line_no}: duplicate meta record")
                meta = row
            elif row.get("rec") == "pkt":
                packets.append(row)
    if meta is None or not isinstance(meta.get("ssid_hex"), str):
        raise ValueError(f"{path}: missing session metadata/ssid_hex")
    return meta, packets


def _source_ip(row: dict[str, Any]) -> str:
    source = row.get("src")
    if not isinstance(source, str) or ":" not in source:
        raise ValueError(f"packet {row.get('seq')}: invalid src")
    return source.rsplit(":", 1)[0]


def _direction(row: dict[str, Any]) -> str:
    value = row.get("dir")
    if value == "in":
        return "peer_to_host"
    if value == "out":
        return "host_to_peer"
    raise ValueError(f"packet {row.get('seq')}: dir must be in/out")


def _protocol_modules(emu_root: Path) -> tuple[Any, Any, Any, Any]:
    """Load the protocol implementation from an explicitly selected checkout."""

    if str(emu_root) not in sys.path:
        sys.path.insert(0, str(emu_root))
    from frlgsim import crypto as crypto_mod, gbaframe as gbaframe_mod
    from frlgsim import reliable as reliable_mod, rfu as rfu_mod
    return crypto_mod, gbaframe_mod, reliable_mod, rfu_mod


def extract(path: str | Path, *, emu_root: str | Path = EMU_ROOT) -> dict[str, Any]:
    """Decode one protocol-agent Pia JSONL capture into a JSON-safe report."""

    jsonl = Path(path)
    emu = Path(emu_root)
    crypto_mod, gbaframe_mod, reliable_mod, rfu_mod = _protocol_modules(emu)
    meta, packets = _load_jsonl(jsonl)
    pia = crypto_mod.PiaCrypto(bytes.fromhex(meta["ssid_hex"]))
    assembler = payload_decoder.RfuBlockAssembler()
    command_counts: dict[str, int] = {}
    blocks: list[dict[str, Any]] = []
    emitted: set[int] = set()
    pending_request: int | None = None

    datagrams = decrypt_failures = reliable_messages = gba_frames = 0
    for row in packets:
        datagrams += 1
        raw_hex = row.get("hex")
        if not isinstance(raw_hex, str):
            raise ValueError(f"packet {row.get('seq')}: missing hex")
        plain = pia.decrypt(bytes.fromhex(raw_hex), _source_ip(row))
        if plain is None:
            decrypt_failures += 1
            continue
        app, compressed = crypto_mod.decompress(plain)
        if plain.startswith(crypto_mod.ZSTD_MAGIC) and not compressed:
            raise RuntimeError("zstandard support is required for this capture")
        messages, _, _ = reliable_mod.parse_app(app)
        for message in messages:
            if message.proto != reliable_mod.PROTO_RELIABLE:
                continue
            reliable_messages += 1
            reliable_frame = reliable_mod.parse_reliable(message.payload)
            if reliable_frame is None or not (reliable_frame.flagsA & 1):
                continue
            result = payload_decoder.parse_gba_frames(reliable_frame.payload)
            for frame in result.frames:
                if frame.frame_type != gbaframe_mod.TYPE_T:
                    continue
                gba_frames += 1
                direction = _direction(row)
                role = "child" if direction == "peer_to_host" else "parent"
                carrier = payload_decoder.parse_t_carrier(frame, role=role)
                if carrier.slot is None:
                    continue
                for command in carrier.slot.commands:
                    command_counts[command.name] = command_counts.get(command.name, 0) + 1
                    block = assembler.feed(
                        command,
                        direction=direction,
                        source_offset=int(row.get("seq", 0)),
                    )
                    if command.opcode == rfu_mod.SEND_BLOCK_REQ and direction == "host_to_peer":
                        pending_request = command.request_type
                    elif (
                        command.opcode == rfu_mod.SEND_BLOCK_INIT
                        and direction == "peer_to_host"
                        and block is not None
                    ):
                        block.request_type = pending_request
                        pending_request = None
                    if block is None or not block.complete or id(block) in emitted:
                        continue
                    emitted.add(id(block))
                    candidates = payload_decoder.scan_pokemon_candidates(
                        block.payload or b"",
                        source_id=f"{direction}:{block.ordinal}",
                        complete=True,
                    )
                    blocks.append({
                        "direction": block.direction,
                        "ordinal": block.ordinal,
                        "expected_fragments": block.expected_fragments,
                        "owner": block.owner,
                        "multiplayer_id": block.multiplayer_id,
                        "request_type": block.request_type,
                        "source_sequences": sorted(set(block.source_offsets)),
                        "size": len(block.payload or b""),
                        "pokemon": [
                            {
                                "offset": candidate.offset,
                                "size": candidate.size,
                                "form": candidate.form,
                                "valid": candidate.valid,
                                "decoded": candidate.decoded,
                                "validation": candidate.validation,
                            }
                            for candidate in candidates
                        ],
                    })
    assembler.finalize()
    stats = ExtractionStats(
        datagrams=datagrams,
        decrypt_failures=decrypt_failures,
        reliable_messages=reliable_messages,
        gba_frames=gba_frames,
        command_counts=command_counts,
    )
    return {
        "schema": "pokemon-payload-report.v1",
        "capture": str(jsonl),
        "stats": asdict(stats),
        "blocks": blocks,
        "issues": [
            {"offset": issue.offset, "code": issue.code, "detail": issue.detail}
            for issue in assembler.issues
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="protocol-agent Pia JSONL capture")
    parser.add_argument("-o", "--output", type=Path, help="write report JSON instead of stdout")
    parser.add_argument("--emu-root", type=Path, default=EMU_ROOT)
    args = parser.parse_args(argv)
    report = extract(args.capture, emu_root=args.emu_root)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["stats"]["decrypt_failures"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
