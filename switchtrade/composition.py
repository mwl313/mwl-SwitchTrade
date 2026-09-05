"""Concrete endpoint selection belongs outside the endpoint-neutral Core."""

from switchtrade.endpoints.switch_ldn import SwitchLdnEndpointDriver


def create_switch_ldn_driver() -> SwitchLdnEndpointDriver:
    return SwitchLdnEndpointDriver()
