#!/usr/bin/env python3
"""Interactive serial REPL backed by the command dictionaries.

Features:
- Tab-completion of command names from ``serial_commands.COMMANDS``.
- ``help`` / ``?`` for a grouped command list.
- ``help <CMD>`` for per-command metadata (parameters, returns, example).

The REPL accepts either a full free-form line (sent verbatim) or a
``<COMMAND>`` followed by space-/comma-separated parameters, which will be
assembled using ``build_command``.
"""
from __future__ import annotations

import readline  # noqa: F401  # enables default tab completion history on *nix
import sys
from pathlib import Path
from typing import List

# Allow importing helper modules from ../code
sys.path.append(str(Path(__file__).parent.parent / "code"))

from serial_commands import (  # type: ignore  # added to path at runtime
    ASYNC_MESSAGES,
    COMMANDS,
    COMMAND_GROUPS,
    build_command,
    is_async_message,
)
from serial_devices_handler import SerialDevice, list_serial_ports, parse_args_base


# ---------- helpers -------------------------------------------------------


def _print_command_help(cmd_name: str) -> None:
    meta = COMMANDS[cmd_name]
    print(f"{cmd_name} ({meta['section']})")
    print(f"  parameters: {meta['parameters']}")
    print(f"  returns:    {meta['returns']}")
    desc = meta.get("description")
    if desc:
        print(f"  desc:       {desc}")
    example = meta.get("example")
    if example:
        print(f"  example:    {example}")


def _print_all_commands() -> None:
    for section, names in COMMAND_GROUPS.items():
        print(f"[{section}]")
        print("  " + "  ".join(names))
    if ASYNC_MESSAGES:
        print("[ASYNC MESSAGES]")
        print("  " + "  ".join(ASYNC_MESSAGES))


def _setup_completion() -> None:
    commands = sorted(COMMANDS.keys())

    def completer(text: str, state: int):
        matches = [c for c in commands if c.startswith(text.upper())]
        return (matches + [None])[state]

    readline.parse_and_bind("tab: complete")
    readline.set_completer(completer)


def _build_payload(user_input: str) -> str:
    """Return the outbound payload.

    If the first token matches a known command, build it with comma-separated
    params; otherwise send the line verbatim so manual/experimental commands
    still work.
    """
    if not user_input:
        return ""

    parts = user_input.split()
    cmd_name = parts[0].upper()

    if cmd_name in COMMANDS:
        # Allow either space or comma separated params after the command name.
        param_str = " ".join(parts[1:])
        if param_str:
            raw_params = [p for p in param_str.replace(",", " ").split() if p]
            return build_command(cmd_name, *raw_params)
        return cmd_name

    return user_input


# ---------- main ---------------------------------------------------------


def main() -> int:
    ap = parse_args_base("Interactive serial REPL (type commands, Ctrl+C to exit)")
    ap.add_argument("--list-commands", action="store_true", help="Print available commands and exit")
    args = ap.parse_args()

    if args.list_ports:
        ports = list_serial_ports()
        print("\n".join(ports) if ports else "No serial ports found.")
        return 0

    if args.list_commands:
        _print_all_commands()
        return 0

    if not args.port:
        print("Please provide --port. Available ports:", list_serial_ports())
        return 2

    dev = SerialDevice(
        port=args.port,
        baud=args.baud,
        timeout_s=args.timeout,
        eol=args.eol.encode("utf-8").decode("unicode_escape"),
        debug=not args.quiet,
    )

    dev.open()
    _setup_completion()
    print("Connected. Type commands like: APP_PING / TARGET_SET_POS 1500 2000")
    print("Type 'help' or '?' for list; 'help CMD' for details; Ctrl+C to exit.")

    try:
        while True:
            try:
                user_line = input("cmd> ").strip()
            except EOFError:
                break

            if not user_line:
                continue

            if user_line.lower() in {"help", "?"}:
                _print_all_commands()
                continue

            if user_line.lower().startswith("help "):
                name = user_line.split(maxsplit=1)[1].upper()
                if name in COMMANDS:
                    _print_command_help(name)
                else:
                    print(f"Unknown command '{name}'. Try again or type 'help'.")
                continue

            payload = _build_payload(user_line)
            if not payload:
                continue

            lines: List[str] = dev.query(payload, expect_prefix=None, extra_read_window_s=0.5)
            if not lines:
                print("(no response)")
                continue

            for ln in lines:
                prefix = "[ASYNC] " if is_async_message(ln) else ""
                print(f"{prefix}{ln}")
    except KeyboardInterrupt:
        print("\nBye.")
    finally:
        dev.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# python serial_repl.py --port /dev/ttyACM0
