"""Production WSL probes used by control-owned D5, D8, and D9 verification."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from typing import Callable, Iterable
import uuid

from switchtrade.connection.p0 import run_command


class DProbeError(RuntimeError):
    pass


_PROCESS_PROGRAM = r"""
import json,os,sys
from pathlib import Path
def ticks(pid):
    path=Path('/proc')/str(pid)/'stat'
    if not path.exists(): return None
    return int(path.read_text(encoding='ascii').rsplit(')',1)[1].split()[19])
run_id=sys.argv[1]
endpoint=int(sys.argv[2]); wrapper=int(sys.argv[3])
matching=0
for item in Path('/proc').iterdir():
    if not item.name.isdigit(): continue
    if item.name==str(os.getpid()): continue
    try:
        command=(item/'cmdline').read_bytes().replace(b'\0',b' ').decode('utf-8','replace')
    except OSError:
        continue
    if run_id in command: matching+=1
print(json.dumps({'endpoint_actual':ticks(endpoint),'wrapper_actual':ticks(wrapper),
                  'matching_processes':matching},separators=(',',':'),sort_keys=True))
""".strip()


_RADIO_PROGRAM = r"""
import json,os,sys
from pathlib import Path
run_id,phy,base=sys.argv[1:4]
suffix=run_id.replace('-','')[:8]
owned={f'sta-a-{suffix}',f'ap-b-{suffix}',f'mon-b-{suffix}',f'tap-b-{suffix}'}
base_path=Path('/sys/class/net')/base
try:
    base_valid=base_path.exists() and (base_path/'phy80211').resolve(strict=True).name==phy
except OSError:
    base_valid=False
if not base_valid:
    print(json.dumps({'status':'unknown','owned_interfaces':None,
                      'driver_threads':None,'phy_active':None},separators=(',',':')))
    raise SystemExit(0)
present=sum((Path('/sys/class/net')/name).exists() for name in owned)
active=False
for item in Path('/sys/class/net').iterdir():
    try:
        link=item/'phy80211'
        same_phy=link.exists() and link.resolve(strict=True).name==phy
        run_owned=item.name in owned
        if same_phy or run_owned:
            flags=int((item/'flags').read_text(encoding='ascii').strip(),0)
            active=active or bool(flags & 1)
    except (OSError,ValueError):
        print(json.dumps({'status':'unknown','owned_interfaces':None,
                          'driver_threads':None,'phy_active':None},separators=(',',':')))
        raise SystemExit(0)
threads=0
for item in Path('/proc').iterdir():
    if not item.name.isdigit(): continue
    if item.name==str(os.getpid()): continue
    try:
        command=(item/'cmdline').read_bytes().replace(b'\0',b' ').decode('utf-8','replace')
    except OSError:
        continue
    if run_id in command: threads+=1
clean=present==0 and threads==0 and not active
print(json.dumps({'status':'quiescent' if clean else 'active','owned_interfaces':present,
                  'driver_threads':threads,'phy_active':active},separators=(',',':'),sort_keys=True))
""".strip()


class WslDProbes:
    """Read-only probes for one exact WSL endpoint launch and selected PHY."""

    def __init__(
        self,
        *,
        distro: str,
        packaged_python: str,
        private_paths: Iterable[str | Path] = (),
        runner: Callable[[list[str], float], subprocess.CompletedProcess[str]] = run_command,
        timeout: float = 5.0,
    ):
        if not isinstance(distro, str) or not distro or not isinstance(packaged_python, str) or not packaged_python:
            raise ValueError("D WSL probe runtime is invalid")
        if timeout <= 0:
            raise ValueError("D WSL probe timeout is invalid")
        self.distro = distro
        self.packaged_python = packaged_python
        paths = tuple(Path(item).resolve(strict=False) for item in private_paths)
        if len(paths) > 16:
            raise ValueError("D private path inventory exceeds its bound")
        self.private_paths = paths
        self.runner = runner
        self.timeout = timeout

    def _json(self, program: str, *arguments: object) -> dict:
        command = [
            "wsl.exe", "-d", self.distro, "-u", "root", "--",
            self.packaged_python, "-c", program, *(str(item) for item in arguments),
        ]
        try:
            result = self.runner(command, self.timeout)
            value = json.loads(result.stdout) if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, TypeError, ValueError) as error:
            raise DProbeError("WSL cleanup state is unavailable") from error
        if not isinstance(value, dict):
            raise DProbeError("WSL cleanup evidence is invalid")
        return value

    def process_start_ticks(self, pid: int) -> int | None:
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise DProbeError("endpoint PID is invalid")
        value = self._json(_PROCESS_PROGRAM, "probe-only", pid, pid).get("endpoint_actual")
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
            raise DProbeError("endpoint process generation is invalid")
        return value

    def launch(self, identity: dict) -> dict:
        try:
            endpoint_pid = identity["endpoint_pid"]
            endpoint_ticks = identity["endpoint_start_ticks"]
            wrapper_pid = identity["wrapper_pid"]
            wrapper_ticks = identity["process_start_ticks"]
            run_id = identity["run_id"]
        except (KeyError, TypeError) as error:
            raise DProbeError("endpoint launch identity is incomplete") from error
        try:
            run_id = str(uuid.UUID(str(run_id)))
        except (TypeError, ValueError, AttributeError) as error:
            raise DProbeError("endpoint run identity is unavailable") from error
        value = self._json(_PROCESS_PROGRAM, run_id, endpoint_pid, wrapper_pid)
        actual_endpoint = value.get("endpoint_actual")
        actual_wrapper = value.get("wrapper_actual")
        matching = value.get("matching_processes")
        if (
            (actual_endpoint is not None and
             (not isinstance(actual_endpoint, int) or isinstance(actual_endpoint, bool))) or
            (actual_wrapper is not None and
             (not isinstance(actual_wrapper, int) or isinstance(actual_wrapper, bool))) or
            not isinstance(matching, int) or isinstance(matching, bool) or matching < 0
        ):
            raise DProbeError("endpoint launch evidence is invalid")
        endpoint_exited = actual_endpoint is None or actual_endpoint != endpoint_ticks
        wrapper_exited = actual_wrapper is None or actual_wrapper != wrapper_ticks
        token_absent = all(not path.exists() for path in self.private_paths)
        clean = endpoint_exited and wrapper_exited and matching == 0 and token_absent
        return {
            "status": "absent" if clean else "present",
            "endpoint_exited": endpoint_exited,
            "wrapper_exited": wrapper_exited,
            "children_absent": matching == 0,
            "token_absent": token_absent,
            "session_absent": matching == 0,
        }

    def radio(self, identity: dict) -> dict:
        try:
            run_id = str(uuid.UUID(str(identity["run_id"])))
            phy = identity["phy"]
            base = identity["netdev"]
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise DProbeError("radio identity is incomplete") from error
        if (not isinstance(phy, str) or re.fullmatch(r"phy[0-9]+", phy) is None or
                not isinstance(base, str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", base) is None):
            raise DProbeError("radio identity is invalid")
        value = self._json(_RADIO_PROGRAM, run_id, phy, base)
        fields = {"status", "owned_interfaces", "driver_threads", "phy_active"}
        if set(value) != fields:
            raise DProbeError("radio cleanup evidence is invalid")
        return value

    def temporary_interfaces(self, identity: dict) -> dict:
        value = self.radio(identity)
        if value["status"] == "unknown":
            return {"status": "unknown", "owned_interfaces": None}
        return {
            "status": "quiescent" if value["owned_interfaces"] == 0 else "active",
            "owned_interfaces": value["owned_interfaces"],
        }


__all__ = ["DProbeError", "WslDProbes"]
