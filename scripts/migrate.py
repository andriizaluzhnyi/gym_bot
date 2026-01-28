#!/usr/bin/env python
"""Helper script for Alembic migrations."""

import argparse
import subprocess
import sys


def run_command(cmd: list[str]) -> int:
    """Run a command and return exit code."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    return result.returncode


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Alembic migration helper")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Create migration
    create = subparsers.add_parser("create", help="Create a new migration")
    create.add_argument("message", help="Migration message")
    create.add_argument(
        "--auto", action="store_true", help="Use autogenerate"
    )

    # Upgrade
    upgrade = subparsers.add_parser("upgrade", help="Upgrade database")
    upgrade.add_argument(
        "target", nargs="?", default="head", help="Target revision (default: head)"
    )

    # Downgrade
    downgrade = subparsers.add_parser("downgrade", help="Downgrade database")
    downgrade.add_argument(
        "target", nargs="?", default="-1", help="Target revision (default: -1)"
    )

    # Current
    subparsers.add_parser("current", help="Show current revision")

    # History
    subparsers.add_parser("history", help="Show revision history")

    # Check
    subparsers.add_parser("check", help="Check if migrations are up to date")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Build alembic command
    if args.command == "create":
        cmd = ["alembic", "revision", "-m", args.message]
        if args.auto:
            cmd.insert(2, "--autogenerate")
    elif args.command == "upgrade":
        cmd = ["alembic", "upgrade", args.target]
    elif args.command == "downgrade":
        cmd = ["alembic", "downgrade", args.target]
    elif args.command == "current":
        cmd = ["alembic", "current"]
    elif args.command == "history":
        cmd = ["alembic", "history", "--verbose"]
    elif args.command == "check":
        cmd = ["alembic", "check"]
    else:
        print(f"Unknown command: {args.command}")
        return 1

    return run_command(cmd)


if __name__ == "__main__":
    sys.exit(main())
