"""Experimental ApEngine prototypes retained for development work.

Production SwitchTrade does not select this registry. Its canonical policy is
``config/wsl-radio-hardware.tsv`` and its only available host engine is
``HostTransport + ldn.create_network()``. The hostapd and direct-nl80211 paths here
remain In Development because neither implements the complete Nintendo LDN lifecycle.

Do not infer product support from CARD_REGISTRY or preferred_engine; those fields only
select a prototype in isolated engine tests.
"""

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from typing import Optional


class EngineNotImplemented(NotImplementedError):
    """Raised when a card's preferred engine exists only as a stub."""


class EngineNotAvailable(RuntimeError):
    """Raised when the engine binary/dependency is missing on this host."""


# ---------------------------------------------------------------------------
# Prototype-only registry. Product card/driver policy lives in the TSV matrix.
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class CardProfile:
    usb_id: str                      # "vendor:product" per lsusb
    name: str                        # human-readable chip name
    driver_hint: str                 # kernel driver module name
    preferred_engine: Optional[str]  # "hostapd" | "nl80211" | None (guest-only)
    hostapd_opts: tuple[str, ...] = ()   # extra hostapd.conf lines, e.g. ("ieee80211n=1",)
    notes: str = ""


CARD_REGISTRY: dict[str, CardProfile] = {
    "0bda:818b": CardProfile(
        usb_id="0bda:818b", name="RTL8192EU", driver_hint="rtl8xxxu",
        preferred_engine="hostapd",
        notes=("START_AP-only beaconing does not start on rtl8xxxu (docs/19); "
               "hostapd backend required for HOST mode."),
    ),
    "0bda:8179": CardProfile(
        usb_id="0bda:8179", name="RTL8188EU", driver_hint="rtl8xxxu",
        preferred_engine=None,
        notes="GUEST-only per docs/14 hardware matrix.",
    ),
}


def get_card_profile(usb_id: str) -> CardProfile:
    """Look up a card profile by USB ID ('vendor:product', case-insensitive)."""
    key = usb_id.lower()
    if key not in CARD_REGISTRY:
        raise KeyError(
            f"Unknown USB id {usb_id!r}; known cards: {sorted(CARD_REGISTRY)}")
    return CARD_REGISTRY[key]


def detect_usb_id_for_interface(iface: str) -> Optional[str]:
    """Best-effort sysfs lookup of the USB id backing a wireless interface.

    Returns 'vendor:product' or None when the phy is not USB-backed."""
    import glob
    import os

    # iface -> phy via /sys/class/net/<iface>/phy80211/name
    phy_link = f"/sys/class/net/{iface}/phy80211"
    try:
        phy = os.path.basename(os.path.realpath(phy_link))
    except OSError:
        return None
    if not phy.startswith("phy"):
        return None

    # walk the phy's device ancestors looking for idVendor/idProduct pairs
    device = f"/sys/class/ieee80211/{phy}/device"
    seen = 0
    while device and seen < 8:
        vid_path = os.path.join(device, "idVendor")
        pid_path = os.path.join(device, "idProduct")
        if os.path.exists(vid_path) and os.path.exists(pid_path):
            try:
                vid = open(vid_path).read().strip().lower()
                pid = open(pid_path).read().strip().lower()
                return f"{vid}:{pid}"
            except OSError:
                return None
        device = os.path.dirname(device)
        seen += 1

    # some kernels expose the usb device under different parents; last resort scan
    for cand in glob.glob("/sys/bus/usb/devices/*/idVendor"):
        dev_dir = os.path.dirname(cand)
        pid_file = os.path.join(dev_dir, "idProduct")
        if os.path.exists(pid_file):
            return None          # ambiguous without interface mapping - give up honestly
    return None


# ---------------------------------------------------------------------------
# Engine contract
# ---------------------------------------------------------------------------
class ApEngine(ABC):
    """Common contract for HOST-mode AP backends.

    Lifecycle: start() -> wait_station() [join detected] -> game protocol on TAP ->
    stop(). Implementations MUST be usable as async context managers."""

    @abstractmethod
    async def start(self, timeout_s: float = 15.0) -> None:
        """Bring the AP up and confirm it is emitting beacons within timeout_s."""

    @abstractmethod
    async def wait_station(self, timeout_s: float = 120.0) -> str:
        """Resolve with the joining station's MAC once a client associates."""

    @abstractmethod
    async def stop(self) -> None:
        """Tear the AP down and clean up any interfaces/files created."""

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """True while the AP is up and believed to be beaconing."""


def make_ap_engine(profile: CardProfile, *, iface: str, ssid: str,
                   channel: int, app_data: bytes = b"",
                   passphrase: Optional[str] = None,
                   log=print) -> ApEngine:
    """Select and construct the engine named by profile.preferred_engine."""
    engine_name = profile.preferred_engine
    if engine_name == "hostapd":
        from frlgsim.ap_hostapd import HostapdApEngine   # local import: optional dep
        return HostapdApEngine(
            iface=iface, ssid=ssid, channel=channel,
            wpa_passphrase=passphrase, extra_opts=profile.hostapd_opts,
            log=log)
    if engine_name == "nl80211":
        return Nl80211ApEngine(iface=iface, ssid=ssid, channel=channel,
                               app_data=app_data, log=log)
    raise ValueError(f"Card {profile.usb_id} has no preferred engine "
                     f"(guest-only? notes={profile.notes!r})")


class Nl80211ApEngine(ApEngine):
    """Stub for future AP-native drivers (mt76 family). Deliberately unimplemented
    until an MT7612U-class card is in hand (YAGNI). Every method raises."""

    def __init__(self, *, iface: str, ssid: str, channel: int,
                 app_data: bytes = b"", log=print):
        self.iface = iface
        self.ssid = ssid
        self.channel = channel
        self.app_data = app_data
        self._log = log

    def _unsupported(self):
        raise EngineNotImplemented(
            "Nl80211ApEngine is a stub for AP-native drivers (mt76 etc). "
            "rtl8xxxu cards must use the hostapd engine (docs/19).")

    async def start(self, timeout_s: float = 15.0) -> None:
        self._unsupported()

    async def wait_station(self, timeout_s: float = 120.0) -> str:
        self._unsupported()

    async def stop(self) -> None:
        self._unsupported()

    @property
    def is_running(self) -> bool:
        return False
