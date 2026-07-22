"""Regression tests for Docker Compose interpolation contracts."""

from pathlib import Path

import yaml


COMPOSE_PATH = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def test_compose_preserves_host_and_string_defaults():
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    service = compose["services"]["docscan"]
    environment = service["environment"]

    assert service["ports"] == [
        "${ROKID_BIND_HOST:-127.0.0.1}:8000:8000"
    ]
    assert environment["ROKID_KEYMAP"] == "${ROKID_KEYMAP:-}"
    assert environment["ROKID_TRANSCRIBE_MODEL"] == (
        "${ROKID_TRANSCRIBE_MODEL:-gpt-4o-transcribe}"
    )
