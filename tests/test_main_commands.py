from argparse import Namespace

import mail_check_app.main as main_module


class _FakeParser:
    def __init__(self, parsed: Namespace):
        self._parsed = parsed

    def parse_args(self, _argv):
        return self._parsed

    def print_help(self):
        pass


def _prepare_main(monkeypatch, command: str):
    monkeypatch.setattr(main_module, "load_runtime_env", lambda **_: "")
    monkeypatch.setattr(main_module, "ensure_active_profile_required", lambda _cmd: 0)
    monkeypatch.setattr(
        main_module,
        "build_parser",
        lambda: _FakeParser(Namespace(print_cron_line=False, command=command)),
    )


def test_main_dispatches_check_command(monkeypatch) -> None:
    _prepare_main(monkeypatch, "check")
    monkeypatch.setattr("mail_check_app.commands.check_command.run_check_command", lambda _args: 11)

    rc = main_module.main(["check"])

    assert rc == 11


def test_main_dispatches_email_command(monkeypatch, capsys) -> None:
    _prepare_main(monkeypatch, "email")
    monkeypatch.setattr("mail_check_app.commands.check_command.run_email_check", lambda _args: (12, "EMAIL OUT"))

    rc = main_module.main(["email"])

    captured = capsys.readouterr().out
    assert rc == 12
    assert "EMAIL OUT" in captured


def test_main_dispatches_icinga_command(monkeypatch) -> None:
    _prepare_main(monkeypatch, "icinga")
    monkeypatch.setattr("mail_check_app.commands.icinga_command.run_icinga_command", lambda _args: 13)

    rc = main_module.main(["icinga"])

    assert rc == 13


def test_main_dispatches_send_command(monkeypatch) -> None:
    _prepare_main(monkeypatch, "send")
    monkeypatch.setattr("mail_check_app.commands.send_command.run_send_command", lambda _args: 14)

    rc = main_module.main(["send"])

    assert rc == 14


def test_main_dispatches_template_config_command(monkeypatch) -> None:
    _prepare_main(monkeypatch, "template-config")
    monkeypatch.setattr("mail_check_app.commands.template_config_command.run_template_config_command", lambda _args: 15)

    rc = main_module.main(["template-config"])

    assert rc == 15
