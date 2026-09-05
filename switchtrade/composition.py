"""Concrete endpoint selection belongs outside the endpoint-neutral Core."""

from switchtrade.endpoints.switch_ldn import SwitchLdnEndpointDriver, SwitchLdnPolicy


def create_switch_ldn_driver(policy: SwitchLdnPolicy | None = None) -> SwitchLdnEndpointDriver:
    return SwitchLdnEndpointDriver(policy)
