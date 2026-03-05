import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from .cli import build_cron_line, build_parser
from .runtime import ensure_active_profile_required, load_runtime_env


KNOWN_COMMANDS = {"check", "email", "icinga", "send", "template-config"}


def _detect_requested_command(tokens: Sequence[str]) -> str:
    for token in tokens:
        if token in KNOWN_COMMANDS:
            return token
    return ""


def main(argv: Optional[Sequence[str]] = None, script_path: Optional[Path] = None) -> int:
    """Parse CLI input, lazy-load the selected command handler, and return its exit code."""
    cli_args = list(argv) if argv is not None else sys.argv[1:]

    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--config", "-c", default="")
    bootstrap_args, remaining_args = bootstrap.parse_known_args(cli_args)

    help_requested = any(token in {"-h", "--help"} for token in remaining_args)
    requested_command = _detect_requested_command(remaining_args)
    require_active_profile = requested_command in {"check", "email", "icinga"} and not help_requested

    runtime_warning = ""
    try:
        runtime_warning = load_runtime_env(
            config_override=bootstrap_args.config,
            require_active_profile=require_active_profile,
        )
    except Exception as exc:
        print(f"ERROR - failed to load runtime config: {exc}")
        return 3

    parser = build_parser()
    args = parser.parse_args(cli_args)

    if args.print_cron_line:
        effective_script = str(script_path) if script_path else str(Path(__file__).resolve())
        print(build_cron_line(script_path=effective_script))
        return 0

    if not args.command:
        if runtime_warning:
            print(f"HINWEIS - {runtime_warning}")
        parser.print_help()
        return 0

    profile_check_code = ensure_active_profile_required(args.command)
    if profile_check_code != 0:
        return profile_check_code

    if args.command == "check":
        from .commands.check_command import run_check_command

        return run_check_command(args)

    if args.command == "email":
        from .commands.check_command import run_email_check

        exit_code, output = run_email_check(args)
        print(output)
        return exit_code

    if args.command == "icinga":
        from .commands.icinga_command import run_icinga_command

        return run_icinga_command(args)

    if args.command == "send":
        from .commands.send_command import run_send_command

        return run_send_command(args)

    if args.command == "template-config":
        from .commands.template_config_command import run_template_config_command

        return run_template_config_command(args)

    parser.print_help()
    return 0
