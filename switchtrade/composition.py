"""Concrete endpoint selection belongs outside the endpoint-neutral Core."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from switchtrade.endpoints.switch_ldn import SwitchLdnEndpointDriver, SwitchLdnPolicy


def create_switch_ldn_driver(policy: SwitchLdnPolicy | None = None) -> SwitchLdnEndpointDriver:
    from switchtrade.endpoints.switch_ldn import SwitchLdnEndpointDriver
    return SwitchLdnEndpointDriver(policy)


def create_retroarch_gpsp_driver(*, pid=None, port=55435):
    from switchtrade.endpoints.retroarch_gpsp.driver import RetroArchGpspEndpointDriver
    return RetroArchGpspEndpointDriver(pid=pid, port=port)
