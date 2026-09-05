"""Marine Data Fabric — architecture.md §13.

The boundary between source adapters and every future intelligence
component. Adapters already produce unit/CRS/timestamp-normalized
``NormalizedObservation`` objects (architecture.md's Source Adapter ->
Raw Response -> Validation -> Normalization pipeline); the Fabric's own
job is narrower and specific: apply the Temporal Validity Gate (§17)
uniformly, regardless of which adapter produced the observation, and hand
back a fabric-native batch. No future agent is meant to see a raw
provider response — only this.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.fabric.temporal import evaluate_temporal_validity
from app.models.contracts import NormalizedObservation


@dataclass
class FabricBatch:
    requested_time: datetime
    observations: list[NormalizedObservation]

    def missing(self) -> list[NormalizedObservation]:
        return [o for o in self.observations if o.quality.is_missing]

    def valid(self) -> list[NormalizedObservation]:
        return [o for o in self.observations if o.temporal_validity == "VALID"]


def ingest(
    observations: list[NormalizedObservation],
    *,
    requested_time: datetime,
    max_staleness: timedelta,
) -> FabricBatch:
    processed: list[NormalizedObservation] = []
    for obs in observations:
        status = evaluate_temporal_validity(
            observed_at=obs.observed_at,
            valid_from=obs.valid_from,
            valid_to=obs.valid_to,
            retrieved_at=obs.retrieved_at,
            requested_time=requested_time,
            max_staleness=max_staleness,
        )
        processed.append(obs.model_copy(update={"temporal_validity": status}))
    return FabricBatch(requested_time=requested_time, observations=processed)
