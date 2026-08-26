"""Read the shared WSL radio policy used by the launcher and product UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re


DEFAULT_PROFILE_PATH = Path(__file__).resolve().parents[1] / "config" / "wsl-radio-hardware.tsv"
USB_ID = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")
LEGACY_PROFILE_COLUMNS = 8
PROFILE_COLUMNS = 12
SAFE_STATUSES = frozenset({"production-verified", "beta-candidate"})
EXPERIMENTAL_STATUSES = frozenset({"upstream-candidate", "driver-candidate"})
BLOCKED_STATUSES = frozenset({"quarantined"})
KNOWN_STATUSES = SAFE_STATUSES | EXPERIMENTAL_STATUSES | BLOCKED_STATUSES


class HardwarePolicyError(ValueError):
    """A stable, user-actionable hardware policy failure."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


HOST_ENGINES = (
    {
        "id": "ldn",
        "name": "HostTransport + ldn.create_network()",
        "status": "available",
        "selectable": True,
        "default": True,
        "summary": "Proven SwitchTrade room-hosting path; owns AP, monitor, and TAP setup.",
    },
    {
        "id": "hostapd",
        "name": "hostapd AP engine",
        "status": "in-development",
        "selectable": False,
        "default": False,
        "summary": "Generic AP/beacon prototype; Nintendo LDN control and data integration is incomplete.",
    },
    {
        "id": "nl80211",
        "name": "direct nl80211 AP engine",
        "status": "in-development",
        "selectable": False,
        "default": False,
        "summary": "Low-level AP prototype; lifecycle and Nintendo LDN integration are incomplete.",
    },
)


@dataclass(frozen=True)
class HardwareProfile:
    usb_id: str
    strategy: str
    module_file: str | None
    allowed_drivers: tuple[str, ...]
    roles: tuple[str, ...]
    status: str
    auto_select: bool
    notes: str
    model: str = "Unknown USB Wi-Fi adapter"
    chipset: str = "Unknown"
    host_engine: str = "ldn"
    evidence: tuple[str, ...] = ()

    def public(self) -> dict:
        data = asdict(self)
        data["allowed_drivers"] = list(self.allowed_drivers)
        data["roles"] = list(self.roles)
        data["evidence"] = list(self.evidence)
        data["operational"] = any(role in {"host", "guest", "relay"} for role in self.roles)
        data["experimental"] = self.status in EXPERIMENTAL_STATUSES
        data["blocked"] = self.status in BLOCKED_STATUSES
        data["selectable"] = data["operational"] and not data["blocked"]
        return data


def host_engines_public() -> list[dict]:
    return [dict(engine) for engine in HOST_ENGINES]


def load_profiles(path: str | Path = DEFAULT_PROFILE_PATH) -> tuple[HardwareProfile, ...]:
    profiles = []
    seen = set()
    for line_number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw or raw.startswith("#"):
            continue
        columns = raw.split("\t")
        if len(columns) not in {LEGACY_PROFILE_COLUMNS, PROFILE_COLUMNS}:
            raise ValueError(
                f"{path}:{line_number}: expected {LEGACY_PROFILE_COLUMNS} or "
                f"{PROFILE_COLUMNS} tab-separated columns"
            )
        usb_id, strategy, module_file, drivers, roles, status, auto_select, notes = columns[:8]
        model, chipset, host_engine, evidence = (
            columns[8:] if len(columns) == PROFILE_COLUMNS else
            ["Unknown USB Wi-Fi adapter", "Unknown", "ldn", ""]
        )
        usb_id = usb_id.lower()
        if not USB_ID.fullmatch(usb_id):
            raise ValueError(f"{path}:{line_number}: invalid USB ID {usb_id!r}")
        if usb_id in seen:
            raise ValueError(f"{path}:{line_number}: duplicate USB ID {usb_id}")
        if auto_select not in {"yes", "no"}:
            raise ValueError(f"{path}:{line_number}: auto_select must be yes or no")
        if status not in KNOWN_STATUSES:
            raise ValueError(f"{path}:{line_number}: unknown hardware status {status!r}")
        if host_engine not in {engine["id"] for engine in HOST_ENGINES}:
            raise ValueError(f"{path}:{line_number}: unknown host engine {host_engine!r}")
        if auto_select == "yes" and status not in SAFE_STATUSES:
            raise ValueError(f"{path}:{line_number}: only verified/beta hardware may auto-select")
        seen.add(usb_id)
        profiles.append(HardwareProfile(
            usb_id=usb_id,
            strategy=strategy,
            module_file=None if module_file == "-" else module_file,
            allowed_drivers=tuple(item for item in drivers.split(",") if item),
            roles=tuple(item for item in roles.split(",") if item),
            status=status,
            auto_select=auto_select == "yes",
            notes=notes,
            model=model,
            chipset=chipset,
            host_engine=host_engine,
            evidence=tuple(item for item in evidence.split("|") if item),
        ))
    if not profiles:
        raise ValueError(f"{path}: no hardware profiles")
    auto = [profile.usb_id for profile in profiles if profile.auto_select]
    if len(auto) != 1:
        raise ValueError(f"{path}: expected exactly one auto-select profile, found {auto}")
    return tuple(profiles)


def select_profile(usb_id: str | None = None,
                   path: str | Path = DEFAULT_PROFILE_PATH) -> HardwareProfile:
    """Select an explicit adapter or the registry's sole automatic candidate."""
    profiles = load_profiles(path)
    if usb_id is None:
        return next(profile for profile in profiles if profile.auto_select)
    wanted = usb_id.lower()
    try:
        return next(profile for profile in profiles if profile.usb_id == wanted)
    except StopIteration as error:
        raise ValueError(f"unsupported USB adapter {wanted}") from error


def require_role(profile: HardwareProfile, role: str,
                 *, allow_experimental: bool = False) -> HardwareProfile:
    return require_hardware(profile, role, allow_experimental=allow_experimental)


def require_hardware(profile: HardwareProfile, role: str,
                     *, allow_experimental: bool = False) -> HardwareProfile:
    if profile.status in BLOCKED_STATUSES:
        raise HardwarePolicyError(
            "HARDWARE_QUARANTINED",
            f"{profile.usb_id} is quarantined and cannot be used for a trading attempt",
        )
    if profile.status not in SAFE_STATUSES | EXPERIMENTAL_STATUSES:
        raise HardwarePolicyError(
            "HARDWARE_STATUS_BLOCKED", f"{profile.usb_id} status={profile.status} is not runnable"
        )
    if role not in profile.roles:
        raise HardwarePolicyError(
            "HARDWARE_ROLE_UNSUPPORTED",
            f"{profile.usb_id} status={profile.status} does not support role {role!r}; "
            f"allowed={','.join(profile.roles) or 'none'}"
        )
    require_host_engine(profile.host_engine)
    return profile


def require_host_engine(engine: str) -> str:
    selected = next((item for item in HOST_ENGINES if item["id"] == engine), None)
    if selected is None:
        raise HardwarePolicyError("HOST_ENGINE_UNKNOWN", f"unknown host engine {engine!r}")
    if not selected["selectable"]:
        raise HardwarePolicyError(
            "HOST_ENGINE_IN_DEVELOPMENT",
            f"{selected['name']} is In Development and cannot be selected",
        )
    return engine
