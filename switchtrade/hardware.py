"""Read the shared WSL radio policy used by the launcher and product UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re


DEFAULT_PROFILE_PATH = Path(__file__).resolve().parents[1] / "config" / "wsl-radio-hardware.tsv"
USB_ID = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")
PROFILE_COLUMNS = 8


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

    def public(self) -> dict:
        data = asdict(self)
        data["allowed_drivers"] = list(self.allowed_drivers)
        data["roles"] = list(self.roles)
        data["operational"] = any(role in {"host", "guest", "relay"} for role in self.roles)
        return data


def load_profiles(path: str | Path = DEFAULT_PROFILE_PATH) -> tuple[HardwareProfile, ...]:
    profiles = []
    seen = set()
    for line_number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw or raw.startswith("#"):
            continue
        columns = raw.split("\t", PROFILE_COLUMNS - 1)
        if len(columns) != PROFILE_COLUMNS:
            raise ValueError(f"{path}:{line_number}: expected {PROFILE_COLUMNS} tab-separated columns")
        usb_id, strategy, module_file, drivers, roles, status, auto_select, notes = columns
        usb_id = usb_id.lower()
        if not USB_ID.fullmatch(usb_id):
            raise ValueError(f"{path}:{line_number}: invalid USB ID {usb_id!r}")
        if usb_id in seen:
            raise ValueError(f"{path}:{line_number}: duplicate USB ID {usb_id}")
        if auto_select not in {"yes", "no"}:
            raise ValueError(f"{path}:{line_number}: auto_select must be yes or no")
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


def require_role(profile: HardwareProfile, role: str) -> HardwareProfile:
    if role not in profile.roles:
        raise ValueError(
            f"{profile.usb_id} status={profile.status} does not support role {role!r}; "
            f"allowed={','.join(profile.roles) or 'none'}"
        )
    return profile
