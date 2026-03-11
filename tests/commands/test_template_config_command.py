import os
from types import SimpleNamespace

from dotenv import load_dotenv

from mail_check_app.commands.template_config_command import format_env_value, run_template_config_command


def _args(template_file: str, output: str) -> SimpleNamespace:
    return SimpleNamespace(
        template_file=template_file,
        output=output,
        force=False,
        new_config="",
        set_default=False,
    )


def _setup_project_roots(monkeypatch, tmp_path):
    project_root = tmp_path / "project"
    config_dir = project_root / "config"
    templates_dir = project_root / "vorlagen"
    config_dir.mkdir(parents=True)
    templates_dir.mkdir(parents=True)

    default_env = config_dir / "settings.env"
    default_env.write_text("MAIL_ACTIVE_CONFIG=\n", encoding="utf-8")

    monkeypatch.setattr("mail_check_app.commands.template_config_command.PROJECT_ROOT", project_root)
    monkeypatch.setattr("mail_check_app.commands.template_config_command.DEFAULT_ENV_PATH", default_env)
    monkeypatch.setattr("mail_check_app.runtime.PROJECT_ROOT", project_root)
    monkeypatch.setattr("mail_check_app.runtime.DEFAULT_ENV_PATH", default_env)
    return project_root, config_dir, templates_dir, default_env


def test_run_template_config_command_creates_match_criteria_file(monkeypatch, tmp_path) -> None:
    _project_root, config_dir, templates_dir, _default_env = _setup_project_roots(monkeypatch, tmp_path)
    template = templates_dir / "mail_source.txt"
    template.write_text(
        "Subject: Alarm Mail\n"
        "From: Monitor <monitor@example.net>\n"
        "\n"
        "This is the message body\n",
        encoding="utf-8",
    )
    output = config_dir / "match_criteria_test.env"

    rc = run_template_config_command(_args(str(template), str(output)))

    assert rc == 0
    content = output.read_text(encoding="utf-8")
    assert 'MAIL_SUBJECT_CONTAINS="Alarm Mail"' in content
    assert "MAIL_FROM_CONTAINS=monitor@example.net" in content


def test_run_template_config_command_rejects_protected_settings_path(monkeypatch, tmp_path) -> None:
    _project_root, _config_dir, templates_dir, default_env = _setup_project_roots(monkeypatch, tmp_path)
    template = templates_dir / "mail_source.txt"
    template.write_text("Subject: Alarm\n\nBody\n", encoding="utf-8")

    rc = run_template_config_command(_args(str(template), str(default_env)))

    assert rc == 3


def test_run_template_config_command_rejects_template_outside_vorlagen(monkeypatch, tmp_path) -> None:
    _project_root, config_dir, _templates_dir, _default_env = _setup_project_roots(monkeypatch, tmp_path)
    template = tmp_path / "mail_source.txt"
    template.write_text("Subject: Alarm\n\nBody\n", encoding="utf-8")

    rc = run_template_config_command(_args(str(template), str(config_dir / "match_criteria_x.env")))

    assert rc == 3


def test_run_template_config_command_rejects_output_outside_config(monkeypatch, tmp_path) -> None:
    _project_root, _config_dir, templates_dir, _default_env = _setup_project_roots(monkeypatch, tmp_path)
    template = templates_dir / "mail_source.txt"
    template.write_text("Subject: Alarm\n\nBody\n", encoding="utf-8")

    rc = run_template_config_command(_args(str(template), str(tmp_path / "outside.env")))

    assert rc == 3


def test_run_template_config_command_rejects_new_config_outside_config(monkeypatch, tmp_path) -> None:
    _project_root, config_dir, templates_dir, _default_env = _setup_project_roots(monkeypatch, tmp_path)
    template = templates_dir / "mail_source.txt"
    template.write_text("Subject: Alarm\n\nBody\n", encoding="utf-8")

    args = _args(str(template), str(config_dir / "match_criteria_ok.env"))
    args.new_config = str(tmp_path / "outside_full.env")
    rc = run_template_config_command(args)

    assert rc == 3


def test_format_env_value_round_trip(tmp_path) -> None:
    """format_env_value muss dotenv-kompatible Syntax erzeugen (Round-Trip-Test)."""
    test_cases = [
        "simple",
        "with spaces",
        "it's quoted",
        'say "hello"',
        "back\\slash",
        "apos' and \"quote\"",
        "Server: it's broken",
    ]
    env_file = tmp_path / "test.env"
    for original in test_cases:
        env_file.write_text(f"TEST_KEY={format_env_value(original)}\n", encoding="utf-8")
        # Umgebungsvariable vor dem Laden entfernen
        os.environ.pop("TEST_KEY", None)
        load_dotenv(dotenv_path=env_file, override=True)
        assert os.getenv("TEST_KEY") == original, (
            f"Round-Trip fehlgeschlagen für {original!r}: "
            f"formatiert als {format_env_value(original)!r}, "
            f"zurückgelesen als {os.getenv('TEST_KEY')!r}"
        )
