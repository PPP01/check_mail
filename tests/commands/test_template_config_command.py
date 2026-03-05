from types import SimpleNamespace

from mail_check_app.commands.template_config_command import run_template_config_command
from mail_check_app.runtime import DEFAULT_ENV_PATH


def _args(template_file: str, output: str) -> SimpleNamespace:
    return SimpleNamespace(
        template_file=template_file,
        output=output,
        force=False,
        new_config="",
        set_default=False,
    )


def test_run_template_config_command_creates_match_criteria_file(tmp_path) -> None:
    template = tmp_path / "mail_source.txt"
    template.write_text(
        "Subject: Alarm Mail\n"
        "From: Monitor <monitor@example.net>\n"
        "\n"
        "This is the message body\n",
        encoding="utf-8",
    )
    output = tmp_path / "match_criteria_test.env"

    rc = run_template_config_command(_args(str(template), str(output)))

    assert rc == 0
    content = output.read_text(encoding="utf-8")
    assert "MAIL_SUBJECT_CONTAINS='Alarm Mail'" in content
    assert "MAIL_FROM_CONTAINS=monitor@example.net" in content


def test_run_template_config_command_rejects_protected_settings_path(tmp_path) -> None:
    template = tmp_path / "mail_source.txt"
    template.write_text("Subject: Alarm\n\nBody\n", encoding="utf-8")

    rc = run_template_config_command(_args(str(template), str(DEFAULT_ENV_PATH)))

    assert rc == 3
