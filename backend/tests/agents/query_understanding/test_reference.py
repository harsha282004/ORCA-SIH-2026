"""Deterministic reference resolution — architecture.md §31a. Every test is
pure (no LLM, no network): `resolve_reference` only ever consumes already-
constructed `IntentResult` objects, mirroring exactly what the orchestration
node passes it.
"""
from __future__ import annotations

from app.agents.query_understanding.models import IntentResult, ReferenceDelta
from app.agents.query_understanding.reference import resolve_reference
from app.models.geo import BBox

DEMO_BBOX = BBox(min_lat=12.70, min_lon=73.50, max_lat=13.45, max_lon=75.05)


def _intent(**overrides) -> IntentResult:
    defaults = dict(
        language="en",
        intent_class="safety_check",
        activity="fishing",
        location={
            "type": "named_place",
            "name": "Mangaluru",
            "resolved_bbox": {"min_lat": 12.84, "min_lon": 74.82, "max_lat": 12.90, "max_lon": 74.88},
        },
        time_window={"start": "2026-09-06T00:00:00+00:00", "end": "2026-09-06T12:00:00+00:00"},
        objective="is it safe to fish",
        constraints={},
        requires_route=False,
        requires_pfz_reference=False,
        persona="fisherman",
        refers_to_prior=False,
        reference_type=None,
    )
    defaults.update(overrides)
    return IntentResult(**defaults)


def test_no_prior_intent_returns_the_new_intent_unchanged() -> None:
    intent = _intent(refers_to_prior=True, reference_type="same_query_different_param")
    result = resolve_reference(intent, None, demo_bbox=DEMO_BBOX)
    assert result is intent


def test_not_a_reference_returns_the_new_intent_unchanged() -> None:
    intent = _intent(refers_to_prior=False)
    prior = _intent()
    result = resolve_reference(intent, prior, demo_bbox=DEMO_BBOX)
    assert result is intent


def test_offshore_offset_moves_the_location_west_and_stays_within_demo_bbox() -> None:
    prior = _intent()
    follow_up = _intent(
        refers_to_prior=True,
        reference_type="same_query_different_param",
        reference_delta=ReferenceDelta(offshore_distance_km=20),
        location={"type": "region", "name": "Mangaluru-Udupi coastal Karnataka", "resolved_bbox": DEMO_BBOX.model_dump()},
    )

    result = resolve_reference(follow_up, prior, demo_bbox=DEMO_BBOX)

    assert result.location["type"] == "named_place"
    assert "offshore" in result.location["name"]
    new_bbox = result.location["resolved_bbox"]
    prior_bbox = prior.location["resolved_bbox"]
    prior_center_lon = (prior_bbox["min_lon"] + prior_bbox["max_lon"]) / 2
    new_center_lon = (new_bbox["min_lon"] + new_bbox["max_lon"]) / 2
    # West = smaller longitude in the northern hemisphere's east-positive
    # convention used throughout this demo region.
    assert new_center_lon < prior_center_lon
    assert new_bbox["min_lat"] >= DEMO_BBOX.min_lat
    assert new_bbox["min_lon"] >= DEMO_BBOX.min_lon
    assert new_bbox["max_lat"] <= DEMO_BBOX.max_lat
    assert new_bbox["max_lon"] <= DEMO_BBOX.max_lon


def test_offshore_offset_is_computed_only_by_deterministic_code_never_the_llm() -> None:
    # The LLM-facing RawIntentResult can only ever name a *distance*
    # (reference_delta.offshore_distance_km) — it has no coordinate field
    # at all (see test_raw_intent_schema_has_no_coordinate_or_absolute_
    # timestamp_fields). This test proves the actual number that lands in
    # `resolved_bbox` matches app.gis.distance.offset_point_km exactly,
    # i.e. it was computed here, not copied from anywhere the LLM could
    # have touched.
    from app.gis.distance import offset_point_km

    prior = _intent()
    prior_bbox = prior.location["resolved_bbox"]
    center_lat = (prior_bbox["min_lat"] + prior_bbox["max_lat"]) / 2
    center_lon = (prior_bbox["min_lon"] + prior_bbox["max_lon"]) / 2
    expected_lat, expected_lon = offset_point_km(center_lat, center_lon, west_km=20)

    follow_up = _intent(
        refers_to_prior=True,
        reference_type="same_query_different_param",
        reference_delta=ReferenceDelta(offshore_distance_km=20),
        location={"type": "region", "name": "x", "resolved_bbox": DEMO_BBOX.model_dump()},
    )
    result = resolve_reference(follow_up, prior, demo_bbox=DEMO_BBOX)
    new_bbox = result.location["resolved_bbox"]
    new_center_lat = (new_bbox["min_lat"] + new_bbox["max_lat"]) / 2
    new_center_lon = (new_bbox["min_lon"] + new_bbox["max_lon"]) / 2
    assert new_center_lat == expected_lat
    assert new_center_lon == expected_lon


def test_missing_reference_delta_falls_back_to_inheriting_prior_named_place() -> None:
    prior = _intent()
    follow_up = _intent(
        refers_to_prior=True,
        reference_type="follow_up_explanation",
        location={"type": "region", "name": "Mangaluru-Udupi coastal Karnataka", "resolved_bbox": DEMO_BBOX.model_dump()},
    )
    result = resolve_reference(follow_up, prior, demo_bbox=DEMO_BBOX)
    assert result.location == prior.location


def test_follow_up_naming_its_own_place_is_not_overridden_by_the_prior_turn() -> None:
    prior = _intent()
    follow_up = _intent(
        refers_to_prior=True,
        reference_type="same_query_different_param",
        location={
            "type": "named_place",
            "name": "Udupi",
            "resolved_bbox": {"min_lat": 13.31, "min_lon": 74.72, "max_lat": 13.37, "max_lon": 74.78},
        },
    )
    result = resolve_reference(follow_up, prior, demo_bbox=DEMO_BBOX)
    assert result.location["name"] == "Udupi"


def test_prior_selected_point_takes_precedence_over_prior_named_place() -> None:
    """Phase 6 (task §13/§18): a follow-up naming no new place anchors to
    the exact previously-discussed POINT (a fishing candidate's
    coordinate, say) rather than the whole prior named-place bbox — more
    specific, and it's what lets the single-point pipeline re-run fresh at
    the exact right spot.
    """
    prior = _intent()
    follow_up = _intent(
        refers_to_prior=True,
        reference_type="follow_up_explanation",
        location={"type": "region", "name": "Mangaluru-Udupi coastal Karnataka", "resolved_bbox": DEMO_BBOX.model_dump()},
    )
    prior_selected_point = {"latitude": 12.95, "longitude": 74.60, "label": "Area A", "source": "fishing"}

    result = resolve_reference(follow_up, prior, demo_bbox=DEMO_BBOX, prior_selected_point=prior_selected_point)

    assert result.location["type"] == "named_place"
    assert result.location["name"] == "Area A"
    bbox = result.location["resolved_bbox"]
    center_lat = (bbox["min_lat"] + bbox["max_lat"]) / 2
    center_lon = (bbox["min_lon"] + bbox["max_lon"]) / 2
    assert abs(center_lat - 12.95) < 0.001
    assert abs(center_lon - 74.60) < 0.001


def test_prior_selected_point_clamped_within_demo_bbox() -> None:
    prior = _intent()
    follow_up = _intent(
        refers_to_prior=True,
        reference_type="follow_up_explanation",
        location={"type": "region", "name": "x", "resolved_bbox": DEMO_BBOX.model_dump()},
    )
    # A point right at the demo bbox's northern edge — the resolved bbox
    # must not extend past the configured domain.
    prior_selected_point = {"latitude": DEMO_BBOX.max_lat, "longitude": 74.60, "label": "Area A", "source": "fishing"}

    result = resolve_reference(follow_up, prior, demo_bbox=DEMO_BBOX, prior_selected_point=prior_selected_point)

    assert result.location["resolved_bbox"]["max_lat"] <= DEMO_BBOX.max_lat


def test_no_prior_selected_point_falls_back_to_prior_named_place() -> None:
    # Backward-compatible: omitting prior_selected_point reproduces the
    # exact pre-Phase-6 behavior.
    prior = _intent()
    follow_up = _intent(
        refers_to_prior=True,
        reference_type="follow_up_explanation",
        location={"type": "region", "name": "x", "resolved_bbox": DEMO_BBOX.model_dump()},
    )
    result = resolve_reference(follow_up, prior, demo_bbox=DEMO_BBOX)
    assert result.location == prior.location


def test_reference_delta_missing_offshore_distance_is_a_no_op() -> None:
    prior = _intent()
    follow_up = _intent(
        refers_to_prior=True,
        reference_type="same_query_different_param",
        reference_delta=ReferenceDelta(offshore_distance_km=None),
        location={
            "type": "named_place",
            "name": "Mangaluru",
            "resolved_bbox": {"min_lat": 12.84, "min_lon": 74.82, "max_lat": 12.90, "max_lon": 74.88},
        },
    )
    result = resolve_reference(follow_up, prior, demo_bbox=DEMO_BBOX)
    assert result.location == follow_up.location
