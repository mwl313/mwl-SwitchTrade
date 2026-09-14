"""Causal NI/UNI oracle through the full production path and real stock gpSP.

This models console input, not the closed Nintendo RFU implementation or trade.
The homebrew uses the peripheral's inverted clock; one UNI is never a pass.
"""
import struct

from full_probe import FullStackLaunch, FullStackProbe
from bridge.frlgsim import ni, rfu
from switchtrade.endpoints.retroarch_gpsp.rfu import _gba, GBA_TRANSFER


def parent_frame(timestamp, slot):
    return _gba(GBA_TRANSFER, struct.pack("<I4B", timestamp, len(slot), 0, 0, 0) +
                slot + bytes(-len(slot) % 4))


def command(number, sequence):
    # Native-sized idle -> player IDs -> block request/init/data. No Pokemon
    # data or game state machine is supplied. Counter bytes are homebrew-only.
    if sequence <= 2:
        return bytes(14)  # real all-zero idle traffic, not an empty slot
    op = (0, 0, 0x7700, 0xA100, 0x8800)[sequence - 1] if sequence <= 5 else 0x8900
    return struct.pack("<7H", op | ((sequence - 6) & 31 if sequence > 5 else 0),
                       number, sequence & 0xFFFF, 0x1234, 0x5678, 0xABCD, 0xEF01)


class ClockProbe(FullStackProbe):
    BURST = 12
    async def expect(self, *prefixes):
        if getattr(self, "early_data", None) is not None:
            data, self.early_data = self.early_data, None
            assert data.startswith(prefixes), "CLOCK_UNEXPECTED_EARLY_DATA"
            return data
        return await super().expect(*prefixes)

    async def begin_data(self, number):
        self.timestamp = self.receipt_sequence = 0
        self.number = number
        sender = ni.NISender(bytes(range(26)))
        while not sender.done:
            expected = sender.next_slot()
            data = await self.expect(b"WT")
            assert data[12:12 + data[9]] == expected, "CLOCK_CHILD_NI_MISMATCH"
            h = rfu.parse_llsf_child(expected)
            if h["state"] != rfu.LCOM_NULL:
                self.timestamp += 1
                self.game.press(parent_frame(self.timestamp,
                    ni.parent_recv_ack_slot(h["state"], h["n"], h["phase"])), 7)
                await self.receipt()
        for slot in ni.parent_join_status_slots():
            self.timestamp += 1
            self.game.press(parent_frame(self.timestamp, slot), 7)
            await self.receipt()
            h = int.from_bytes(slot[:3], "little")
            if h >> 14 & 15:
                data = await self.expect(b"WT")
                assert data[12:12 + data[9]] == ni.recv_ack_slot(h >> 14 & 15, h >> 11 & 3, h >> 9 & 3)
        self.offset = 0
        for count in range(self.BURST):
            self.game.press(self.parent_frame(number, count), 7)
        for count in range(1, self.BURST + 1):
            receipt = await self.expect(b"WK")
            self.receipt_sequence += 1
            assert receipt == b"WK\x0c\0" + struct.pack("<III", self.receipt_sequence, 1, self.timestamp - self.BURST + count)
            data = await self.expect(b"WT")
            self.check_data(data, number, count)
        self.offset = self.BURST
        self.game.press(self.parent_frame(number, 0), 7)
        return await self.expect_reply(0)

    async def receipt(self, value=None):
        if value is None:
            value = await super().expect(b"WK", b"WT")
            if value.startswith(b"WT"):
                assert getattr(self, "early_data", None) is None, "CLOCK_DUPLICATE_EARLY_DATA"
                self.early_data = value
                value = await super().expect(b"WK")
        self.receipt_sequence += 1
        assert value == b"WK\x0c\0" + struct.pack("<III", self.receipt_sequence, 1, self.timestamp), "CLOCK_RECEIPT_MISMATCH"

    def parent_frame(self, number, count):
        self.timestamp += 1
        count += self.offset
        rows = [command(number, count + 1), command(number, count) if count else bytes(14)]
        return parent_frame(self.timestamp, rfu.parent_uni_slot(rows))

    async def expect_reply(self, count):
        first = await self.expect(b"WK", b"WT")
        second = await self.expect(b"WT" if first.startswith(b"WK") else b"WK")
        receipt, data = (first, second) if first.startswith(b"WK") else (second, first)
        await self.receipt(receipt)
        if count: # base traffic count excludes the initial UNI bootstrap
            self.receipt_verified += 1
            self.data_before_receipt += first.startswith(b"WT")
        return data

    def check_data(self, data, number, count):
        count += self.offset
        expected = bytearray(command(number, count))
        if count > 2:
            expected[0] |= ((count - 3) & 7) << 5
        slot = rfu.uni_slot(bytes(expected))
        assert (len(data) == 28 and data[:4] == b"WT\x18\0" and data[8:12] == b"\0\x10\0\0"
                and int.from_bytes(data[4:8], "little") != 0)
        assert data[12:] == slot, "CLOCK_UNI_COUNTER_TAG_OR_BYTES_MISMATCH"

    def exchange(self, number):
        result = super().exchange(number)
        result.update(clock_change=True, causal_ni=True, burst_uni_exchanges=self.BURST,
                      parent_rows=5, child_tag_wrap=True)
        return result


class ClockLaunch(FullStackLaunch):
    probe_type = ClockProbe
