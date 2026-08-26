"""Bounded, passive observer for locally terminated RFU AppData."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import queue
import secrets
import threading
from typing import Callable

from tools import payload_decoder


PARTY_CONTRACT = "party-commit.v1"
READY_TO_TRADE = 0xAABB
SET_MONS_TO_TRADE = 0xDDDD
START_TRADE = 0xCCDD
READY_FINISH_TRADE = 0xABCD
CONFIRM_FINISH_TRADE = 0xDCBA
CANCEL_COMMANDS = {0xEEAA, 0xBBCC, 0xDDEE, 0xEEBB, 0xEECC}
NATURES = (
    "Hardy", "Lonely", "Brave", "Adamant", "Naughty",
    "Bold", "Docile", "Relaxed", "Impish", "Lax",
    "Timid", "Hasty", "Serious", "Jolly", "Naive",
    "Modest", "Mild", "Quiet", "Bashful", "Rash",
    "Calm", "Gentle", "Sassy", "Careful", "Quirky",
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _field(value, provenance: str = "observed") -> dict:
    return {"value": value, "provenance": provenance}


class PassivePartyObserver:
    """Decode copies on a worker thread; overflow can never block RFU forwarding."""

    def __init__(self, path: str | Path, attempt_id: str, local_seat: str,
                 *, capacity: int = 256, log: Callable[..., None] = lambda *_: None):
        if local_seat not in {"member_a", "member_b"}:
            raise ValueError("local_seat must be member_a or member_b")
        self.path = Path(path)
        self.attempt_id = attempt_id
        self.local_seat = local_seat
        self.remote_seat = "member_b" if local_seat == "member_a" else "member_a"
        self.log = log
        self._write_lock = threading.RLock()
        self._queue: queue.Queue[tuple[str, str, bytes]] = queue.Queue(maxsize=capacity)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="switchtrade-decoder", daemon=True)
        self._assemblers = {
            "member_a": payload_decoder.RfuBlockAssembler(),
            "member_b": payload_decoder.RfuBlockAssembler(),
        }
        self._pending_request: dict[str, int] = {}
        self._party_chunks: dict[str, list[list[dict]]] = {"member_a": [], "member_b": []}
        self._emitted: set[int] = set()
        self._versions = {"member_a": 0, "member_b": 0}
        self._parties = {
            seat: {"status": "unavailable", "reason": "awaiting_complete_party", "snapshot": None}
            for seat in ("member_a", "member_b")
        }
        self.stats = {
            "submitted": 0, "processed": 0, "dropped": 0, "parse_errors": 0,
            "complete_blocks": 0, "valid_records": 0, "snapshots": 0, "commits": 0,
            "write_errors": 0,
        }
        self._latest_hashes: dict[str, list[str | None]] = {}
        self._trade_index = 0
        self._commits: dict[str, dict] = {}
        self._reset_trade_evidence()
        self._write("checking")

    def start(self) -> "PassivePartyObserver":
        self._thread.start()
        return self

    def submit(self, source_seat: str, sender_role: str, payload: bytes) -> None:
        """Copy and enqueue without waiting. The caller's primary path always wins."""
        if self._stop.is_set():
            self.stats["dropped"] += 1
            return
        try:
            self._queue.put_nowait((source_seat, sender_role, bytes(payload)))
            self.stats["submitted"] += 1
        except queue.Full:
            self.stats["dropped"] += 1
            self._invalidate(source_seat, "observer_queue_overflow")

    def stop(self, *, clear: bool = True, timeout: float = 2.0) -> None:
        self._stop.set()
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise RuntimeError("passive observer thread did not stop before its cleanup deadline")
        if clear:
            for seat in self._parties:
                self._parties[seat] = {
                    "status": "unavailable", "reason": "session_ended", "snapshot": None,
                }
        self._write("stopped")

    def snapshot(self) -> dict:
        with self._write_lock:
            return {
                "contract_version": PARTY_CONTRACT,
                "attempt_id": self.attempt_id,
                "observer_status": "ready" if self._thread.is_alive() else "stopped",
                "parties": self._parties,
                "trading_room_confirmed": all(
                    party["status"] == "available" for party in self._parties.values()
                ),
                "stats": dict(self.stats),
                "commits": list(self._commits.values()),
                "updated_at": _utc(),
            }

    def _run(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                source_seat, sender_role, payload = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._process(source_seat, sender_role, payload)
                self.stats["processed"] += 1
            except Exception as error:
                self.stats["parse_errors"] += 1
                self._invalidate(source_seat, "decoder_error")
                self.log("[decoder] passive observer error", type(error).__name__)

    def _process(self, source_seat: str, sender_role: str, payload: bytes) -> None:
        result = payload_decoder.parse_gba_frames(payload)
        direction = f"{source_seat}_out"
        response_direction = f"{self.remote_seat if source_seat == self.local_seat else self.local_seat}_out"
        assembler = self._assemblers[source_seat]
        changed = False
        for frame in result.frames:
            if frame.frame_type != 0x54:
                continue
            carrier = payload_decoder.parse_t_carrier(frame, role=sender_role)
            if carrier.slot is None:
                continue
            for command in carrier.slot.commands:
                if command.opcode == 0x6600:
                    self._observe_save_count(source_seat, command.words[1])
                if command.opcode == 0xA100 and command.request_type is not None:
                    self._pending_request[response_direction] = command.request_type
                block = assembler.feed(command, direction=direction)
                if command.opcode == 0x8800 and block is not None:
                    block.request_type = self._pending_request.pop(direction, None)
                if block is None or not block.complete or id(block) in self._emitted:
                    continue
                self._emitted.add(id(block))
                self.stats["complete_blocks"] += 1
                self._observe_completed_block(source_seat, block)
                if block.request_type != 1:
                    continue
                changed |= self._consume_party_block(source_seat, block)
        if changed:
            self._write("ready")

    def _consume_party_block(self, seat: str, block) -> bool:
        raw = block.payload or b""
        if len(raw) < 200:
            return False
        slots: list[dict] = []
        for index in range(2):
            record = raw[index * 100:(index + 1) * 100]
            candidates = payload_decoder.scan_pokemon_candidates(
                record, source_id=f"{seat}:{block.ordinal}:{index}", complete=True,
            )
            candidate = next((item for item in candidates if item.valid and item.offset == 0), None)
            if candidate is None:
                if any(record):
                    self._invalidate(seat, "invalid_pokemon_checksum")
                    return False
                slots.append({"occupied": False})
                continue
            self.stats["valid_records"] += 1
            slots.append(self._pokemon(candidate, index + 1))
        chunks = self._party_chunks[seat]
        chunks.append(slots)
        if len(chunks) < 3:
            return False
        six = [item for chunk in chunks[-3:] for item in chunk]
        self._party_chunks[seat] = []
        self._versions[seat] += 1
        version = self._versions[seat]
        digest = hashlib.sha256("".join(
            slot.get("record_hash", "empty") for slot in six
        ).encode("ascii")).hexdigest()[:20]
        for slot_number, slot in enumerate(six, 1):
            slot["slot"] = slot_number
        self._parties[seat] = {
            "status": "available",
            "reason": None,
            "snapshot": {
                "contract_version": PARTY_CONTRACT,
                "snapshot_id": f"ps_{digest}",
                "snapshot_version": version,
                "attempt_id": self.attempt_id,
                "member_id": seat,
                "observed_at": _utc(),
                "validity": "complete_checksum_valid",
                "slots": six,
            },
        }
        self.stats["snapshots"] += 1
        hashes = [slot.get("record_hash") if slot.get("occupied") else None for slot in six]
        self._latest_hashes[seat] = hashes
        if self._trade["confirmed"]:
            self._trade["post"][seat] = hashes
        else:
            self._trade["pre"][seat] = hashes
        self._try_commit()
        self.log("[decoder] complete party snapshot", seat, f"version={version}")
        return True

    def _observe_completed_block(self, seat: str, block) -> None:
        payload = block.payload or b""
        if len(payload) < 4:
            return
        command = int.from_bytes(payload[:2], "little")
        cursor = int.from_bytes(payload[2:4], "little")
        if command not in {
            READY_TO_TRADE, SET_MONS_TO_TRADE, START_TRADE,
            READY_FINISH_TRADE, CONFIRM_FINISH_TRADE, *CANCEL_COMMANDS,
        }:
            return
        self._observe_link_command(seat, command, cursor)

    def _observe_link_command(self, seat: str, command: int, cursor: int = 0) -> None:
        if command in CANCEL_COMMANDS:
            self._reset_trade_evidence(keep_parties=True)
            return
        if command in {READY_TO_TRADE, SET_MONS_TO_TRADE} and 0 <= cursor < 6:
            self._trade["selections"][seat] = cursor
        elif command == START_TRADE and len(self._trade["selections"]) == 2:
            self._trade["started"] = True
        elif command == READY_FINISH_TRADE and self._trade["started"]:
            self._trade["ready_finish"] = True
        elif command == CONFIRM_FINISH_TRADE and self._trade["started"] and self._trade["ready_finish"]:
            self._trade["confirmed"] = True
        self._try_commit()

    def _observe_save_count(self, seat: str, count: int) -> None:
        if self._trade["confirmed"] and 5 <= count <= 10:
            self._trade["save_counts"][seat].add(count)
            self._try_commit()

    def _try_commit(self) -> None:
        evidence = self._trade
        if not evidence["confirmed"] or set(evidence["post"]) != {"member_a", "member_b"}:
            return
        if any(not set(range(5, 11)).issubset(evidence["save_counts"][seat])
               for seat in ("member_a", "member_b")):
            return
        if set(evidence["pre"]) != {"member_a", "member_b"} or set(evidence["selections"]) != {
                "member_a", "member_b"}:
            return
        a_slot = evidence["selections"]["member_a"]
        b_slot = evidence["selections"]["member_b"]
        pre_a = evidence["pre"]["member_a"][a_slot]
        pre_b = evidence["pre"]["member_b"][b_slot]
        post_a = evidence["post"]["member_a"][a_slot]
        post_b = evidence["post"]["member_b"][b_slot]
        if not pre_a or not pre_b or post_a != pre_b or post_b != pre_a:
            return
        self._trade_index += 1
        canonical_pair = "|".join(sorted((pre_a, pre_b)))
        digest = hashlib.sha256(
            f"{self.attempt_id}|{self._trade_index}|{canonical_pair}".encode("ascii")
        ).hexdigest()[:24]
        commit_id = f"tc_{digest}"
        self._commits.setdefault(commit_id, {
            "contract_version": PARTY_CONTRACT,
            "event": "trade.committed",
            "commit_id": commit_id,
            "attempt_id": self.attempt_id,
            "trade_index": self._trade_index,
            "committed_at": _utc(),
            "outcome": "committed",
            "member_a_record_hash": pre_a,
            "member_b_record_hash": pre_b,
            "evidence": {
                "bilateral_finish": True,
                "bilateral_save": True,
                "post_save_party_rebuild": True,
                "stable_return": True,
            },
            "statistics_eligible": False,
        })
        self.stats["commits"] = len(self._commits)
        self.log("[decoder] fail-closed trade commit", commit_id)
        self._reset_trade_evidence(keep_parties=True)
        self._write("ready")

    def _reset_trade_evidence(self, *, keep_parties: bool = False) -> None:
        pre = dict(self._latest_hashes) if keep_parties else {}
        self._trade = {
            "pre": pre,
            "post": {},
            "selections": {},
            "started": False,
            "ready_finish": False,
            "confirmed": False,
            "save_counts": {"member_a": set(), "member_b": set()},
        }

    @staticmethod
    def _pokemon(candidate, slot: int) -> dict:
        data = candidate.decoded
        stats = list(data.get("stats") or [])
        ivs = list(data.get("ivs") or [])
        evs = list(data.get("evs") or [])
        nature_index = int(data.get("nature", -1))
        moves = list(data.get("moves") or [])
        record_hash = "sha256:" + hashlib.sha256(candidate.canonical).hexdigest()
        result = {
            "slot": slot,
            "occupied": True,
            "record_hash": record_hash,
            "species": _field(data.get("species_name")),
            "nickname": _field(data.get("nickname")),
            "level": _field(data.get("level")),
            "nature": _field(NATURES[nature_index] if 0 <= nature_index < len(NATURES) else None,
                              "derived" if 0 <= nature_index < len(NATURES) else "unavailable"),
            "held_item": _field(data.get("heldItem")),
            "current_hp": _field(stats[0] if len(stats) >= 1 else None),
            "max_hp": _field(stats[1] if len(stats) >= 2 else None),
            "stats": {
                name: _field(stats[index] if len(stats) > index else None)
                for name, index in (("attack", 2), ("defense", 3), ("speed", 4),
                                    ("sp_attack", 5), ("sp_defense", 6))
            },
            "ivs": {
                name: _field(ivs[index] if len(ivs) > index else None)
                for index, name in enumerate(("hp", "attack", "defense", "speed", "sp_attack", "sp_defense"))
            },
            "evs": {
                name: _field(evs[index] if len(evs) > index else None)
                for index, name in enumerate(("hp", "attack", "defense", "speed", "sp_attack", "sp_defense"))
            },
            "moves": [
                {"slot": index + 1, "move_id": _field(move), "name": _field(None, "unavailable")}
                for index, move in enumerate((moves + [0, 0, 0, 0])[:4])
            ],
            "trainer": {
                "name": _field(data.get("otName")),
                "trainer_id": _field(data.get("tid")),
                "secret_id": _field(None, "unavailable"),
                "language": _field(data.get("language")),
            },
        }
        return result

    def _invalidate(self, seat: str, reason: str) -> None:
        if seat not in self._parties:
            return
        with self._write_lock:
            self._party_chunks[seat] = []
            self._parties[seat] = {"status": "unavailable", "reason": reason, "snapshot": None}
            self._write("degraded")

    def _write(self, status: str) -> None:
        with self._write_lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(self.path.suffix + ".tmp")
                data = self.snapshot()
                data["observer_status"] = status
                temporary.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
                temporary.replace(self.path)
            except OSError:
                self.stats["write_errors"] += 1
