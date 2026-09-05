"""Source adapter base — architecture.md's Source Adapter -> Raw Response ->
Validation -> Normalization -> Marine Data Fabric pipeline (Phase 1).

Business logic (agents, later phases) must never import ``httpx`` or know
a provider's response shape directly — that lives entirely behind a
``SourceAdapter`` subclass.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.models.contracts import Mode, NormalizedObservation


class SourceAdapterError(Exception):
    """Base for all source-adapter failures. Never silently swallowed."""


class SourceTimeoutError(SourceAdapterError):
    pass


class SourceHTTPError(SourceAdapterError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class SourceResponseError(SourceAdapterError):
    """Malformed / unexpected response structure — missing field, bad JSON, etc."""


@dataclass
class RawResponse:
    source: str
    request_url: str
    request_params: dict[str, Any]
    retrieved_at: datetime
    payload: dict[str, Any]


class SourceAdapter(ABC):
    """Common HTTP fetch + raw-storage behavior for all Phase 1 adapters."""

    source_name: str

    def __init__(self, *, base_url: str, timeout_seconds: float, raw_data_dir: Path | None = None):
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.raw_data_dir = raw_data_dir

    def _get(self, params: dict[str, Any]) -> RawResponse:
        retrieved_at = datetime.now(timezone.utc)
        try:
            response = httpx.get(self.base_url, params=params, timeout=self.timeout_seconds)
        except httpx.TimeoutException as exc:
            raise SourceTimeoutError(f"{self.source_name} timed out after {self.timeout_seconds}s") from exc
        except httpx.HTTPError as exc:
            raise SourceAdapterError(f"{self.source_name} request failed: {exc}") from exc

        if response.status_code >= 400:
            raise SourceHTTPError(
                response.status_code, f"{self.source_name} returned HTTP {response.status_code}: {response.text[:300]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise SourceResponseError(f"{self.source_name} returned a non-JSON response") from exc

        if not isinstance(payload, dict):
            raise SourceResponseError(f"{self.source_name} returned a non-object JSON payload")

        raw = RawResponse(
            source=self.source_name,
            request_url=str(response.request.url),
            request_params=params,
            retrieved_at=retrieved_at,
            payload=payload,
        )
        if self.raw_data_dir is not None:
            self._persist_raw(raw)
        return raw

    def _persist_raw(self, raw: RawResponse) -> None:
        """Preserve source/retrieval-time/request-params/payload verbatim under
        data/raw/ — architecture.md §42 (raw storage never mixes with normalized data).
        Never writes secrets: request_params here are geographic/temporal only,
        Open-Meteo requires no API key.
        """
        self.raw_data_dir.mkdir(parents=True, exist_ok=True)
        stamp = raw.retrieved_at.strftime("%Y%m%dT%H%M%S%fZ")
        out_path = self.raw_data_dir / f"{raw.source}_{stamp}.json"
        out_path.write_text(
            json.dumps(
                {
                    "source": raw.source,
                    "request_url": raw.request_url,
                    "request_params": raw.request_params,
                    "retrieved_at": raw.retrieved_at.isoformat(),
                    "payload": raw.payload,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    @abstractmethod
    def fetch(self, *, latitude: float, longitude: float) -> RawResponse:
        """Perform the live request. Raises a SourceAdapterError subclass on failure."""

    @abstractmethod
    def parse(self, raw: RawResponse, *, mode: Mode) -> list[NormalizedObservation]:
        """Validate + normalize a raw payload into NormalizedObservation objects.
        Malformed/missing fields must never silently become a fabricated value —
        they become an explicit `quality.is_missing` observation instead, or a
        raised SourceResponseError if the payload is unusable at the structural level.
        """
