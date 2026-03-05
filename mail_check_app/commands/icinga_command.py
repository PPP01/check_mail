from ..shared.icinga_api import missing_icinga_args, submit_passive_result


def run_icinga_command(args) -> int:
    """Submit a synthetic test result to Icinga and return plugin-style exit code."""
    missing = missing_icinga_args(args)
    if missing:
        print(f"UNKNOWN - Icinga settings missing: {', '.join(missing)}")
        return 3

    try:
        submit_status = submit_passive_result(args, args.test_exit_status, args.test_output)
        print(f"Icinga submit OK - {submit_status}")
    except Exception as exc:
        print(f"UNKNOWN - Icinga submit failed: {exc}")
        return 3

    print(
        f"TEST - icinga command submitted test payload "
        f"(exit_status={args.test_exit_status}, output={args.test_output!r})"
    )
    return 0
