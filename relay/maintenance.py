"""Offline-safe relay authority backup and restore commands."""

from __future__ import annotations

import argparse

from relay.authority import copy_database


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("backup", "restore"))
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    copy_database(args.source, args.destination)
    print(f"{args.operation} verified")


if __name__ == "__main__":
    main()
