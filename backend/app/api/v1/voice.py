"""Voice output endpoint — Phase 9 (Ask ORCA text-to-speech).

`POST /voice/speak` — server-side ElevenLabs synthesis, never exposing the
API key to the browser (task's own "backend environment variables" rule).
The credential lives only in `app.config.Settings` (read from
`ELEVENLABS_API_KEY`); `app.voice.elevenlabs.synthesize` makes the single
real HTTP call. When no key is configured (the default in this
deployment — see docs/PHASE_12_..._REPORT.md §13), this returns a
structured 503 disclosing exactly that, never a 200 with silent/fabricated
audio — matching the task's explicit "handle the failure honestly rather
than silently claiming it worked."
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.voice.elevenlabs import TTSUnavailableError, synthesize

router = APIRouter(prefix="/voice", tags=["voice"])


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    # Accepted so the request's intent is explicit and logged — see
    # app.voice.elevenlabs's own docstring for why it doesn't change the
    # actual synthesis call.
    language: str = "en"


@router.post("/speak")
def speak(request: SpeakRequest, settings: Settings = Depends(get_settings)) -> Response:
    try:
        audio = synthesize(
            text=request.text,
            language=request.language,
            api_key=settings.elevenlabs_api_key,
            voice_id=settings.elevenlabs_voice_id,
            model_id=settings.elevenlabs_model_id,
        )
    except TTSUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"available": False, "reason": str(exc)}) from exc

    return Response(content=audio, media_type="audio/mpeg")
