"""Phase 9 — Ask ORCA voice output (`POST /api/v1/voice/speak`).

`ELEVENLABS_API_KEY` is empty in every test environment (never a real
credential in CI/tests) — these tests verify the endpoint reports that
honestly (a structured 503, never a 200 with fabricated/empty audio),
plus the pure `synthesize()` unit-level guards.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.voice.elevenlabs import TTSUnavailableError, synthesize

client = TestClient(app)


def test_speak_without_configured_key_returns_honest_503() -> None:
    response = client.post("/api/v1/voice/speak", json={"text": "Conditions are safe.", "language": "en"})
    assert response.status_code == 503
    body = response.json()["detail"]
    assert body["available"] is False
    assert "not configured" in body["reason"].lower()


def test_speak_rejects_empty_text() -> None:
    response = client.post("/api/v1/voice/speak", json={"text": "", "language": "en"})
    assert response.status_code == 422  # Pydantic min_length — never silently synthesized as empty audio


def test_synthesize_raises_when_key_missing() -> None:
    with pytest.raises(TTSUnavailableError, match="not configured"):
        synthesize(text="hello", language="en", api_key="", voice_id="", model_id="eleven_multilingual_v2")


def test_synthesize_raises_when_voice_id_missing_even_with_key() -> None:
    with pytest.raises(TTSUnavailableError, match="not configured"):
        synthesize(text="hello", language="en", api_key="fake-key", voice_id="", model_id="eleven_multilingual_v2")


def test_synthesize_raises_on_blank_text() -> None:
    with pytest.raises(TTSUnavailableError, match="No response text"):
        synthesize(text="   ", language="en", api_key="fake-key", voice_id="fake-voice", model_id="eleven_multilingual_v2")
