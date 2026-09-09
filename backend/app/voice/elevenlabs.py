"""ElevenLabs text-to-speech — Phase 9 (Ask ORCA voice output).

Server-side only: `ELEVENLABS_API_KEY` never reaches the frontend (task's
own "DO NOT hardcode or expose API keys in frontend code" rule). This
module makes exactly one real HTTP call per synthesis request — no
fabricated audio, no silent success when the key is missing or the
provider call fails. `synthesize()` raises `TTSUnavailableError` in both
cases; the caller (app.api.v1.voice) turns that into an honest 503, never
a 200 with placeholder/empty audio.

Language handling: ElevenLabs' `eleven_multilingual_v2` model is
documented to speak many languages from a single voice, inferring
pronunciation from the input text itself — there is no separate
"language" parameter to set. The `language` argument here is accepted only
so the caller's intent is explicit in logs/errors; it does not change the
request. If ElevenLabs cannot actually render the requested language well
(unverified for Kannada specifically as of this integration — see
docs/PHASE_12_..._REPORT.md's own disclosure), that surfaces as an
audibly wrong/empty response from the real API, never something this
module papers over.
"""
from __future__ import annotations

import httpx

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


class TTSUnavailableError(Exception):
    """Raised whenever real speech audio cannot be produced — missing
    configuration or a genuine upstream failure. Never caught silently;
    the API layer converts this into a structured, honest error response."""


def synthesize(*, text: str, language: str, api_key: str, voice_id: str, model_id: str, timeout_seconds: float = 20.0) -> bytes:
    if not api_key or not voice_id:
        raise TTSUnavailableError(
            "ElevenLabs is not configured in this deployment (ELEVENLABS_API_KEY/ELEVENLABS_VOICE_ID are empty) — "
            "voice output is unavailable, not silently skipped."
        )
    if not text.strip():
        raise TTSUnavailableError("No response text was provided to synthesize.")

    url = ELEVENLABS_TTS_URL.format(voice_id=voice_id)
    headers = {"xi-api-key": api_key, "content-type": "application/json", "accept": "audio/mpeg"}
    payload = {"text": text, "model_id": model_id}

    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=timeout_seconds)
    except httpx.HTTPError as exc:
        raise TTSUnavailableError(f"ElevenLabs request failed: {exc}") from exc

    if response.status_code >= 400:
        raise TTSUnavailableError(f"ElevenLabs returned HTTP {response.status_code}: {response.text[:300]}")

    audio = response.content
    if not audio:
        raise TTSUnavailableError("ElevenLabs returned an empty audio payload.")
    return audio
