"""Stable errors owned by the Switch LDN endpoint boundary."""

from __future__ import annotations


class SwitchLdnEndpointError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
