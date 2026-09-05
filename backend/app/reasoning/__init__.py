"""Deterministic reasoning-layer components — architecture.md §17-20 and
§22's confidence formula.

Phase 2 implements only ``confidence`` here (see confidence.py). Temporal
validity was already implemented in Phase 1 (``app.fabric.temporal`` —
tightly coupled to the Fabric's ingestion pipeline, a reasonable reading of
the architecture given §17 sits directly inside the Fabric's own
responsibilities). Spatial-temporal fusion, evidence arbitration, and
conflict resolution (§18-20) require reconciling *multiple* agents'
evidence for the same factor — that need doesn't exist until real data
agents exist (Phase 4+), so those remain unimplemented here, deliberately.
"""
