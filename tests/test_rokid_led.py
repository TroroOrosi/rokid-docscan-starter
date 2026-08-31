"""The former indicator-modification experiment is permanently quarantined."""

from app.devtools.rokid_led import quarantine_reason
from scripts.rokid_led import main


def test_quarantine_reason_is_explicit():
    reason = quarantine_reason()
    assert "unsupported" in reason.lower()
    assert "indicator" in reason.lower()


def test_cli_never_accepts_an_operation(capsys):
    assert main([]) == 2
    assert "unsupported" in capsys.readouterr().err.lower()


def test_cli_ignores_legacy_write_arguments(capsys):
    assert main(["disable", "--apply", "--force"]) == 2
    assert "unsupported" in capsys.readouterr().err.lower()
