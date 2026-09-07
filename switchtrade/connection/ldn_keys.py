"""Validate the key-file shape for the pinned production LDN protocol (v3)."""


def valid_keys(keys) -> bool:
    return isinstance(keys, dict) and all(
        isinstance(keys.get(name), bytes) and len(keys[name]) == 16
        for name in ("master_key_12", "aes_kek_generation_source", "aes_key_generation_source")
    )
