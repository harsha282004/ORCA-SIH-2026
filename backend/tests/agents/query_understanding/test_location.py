from app.agents.query_understanding.location import resolve_location
from app.models.geo import BBox

DEMO_BBOX = BBox(min_lat=12.70, min_lon=73.50, max_lat=13.45, max_lon=75.05)


def test_empty_location_name_resolves_to_full_demo_region() -> None:
    result = resolve_location(None, demo_bbox=DEMO_BBOX)
    assert result["type"] == "region"
    assert result["resolved_bbox"] == DEMO_BBOX.model_dump()


def test_known_place_resolves_to_a_clipped_buffer_bbox() -> None:
    result = resolve_location("Mangaluru", demo_bbox=DEMO_BBOX)
    assert result["type"] == "named_place"
    bbox = result["resolved_bbox"]
    assert bbox["min_lat"] < 12.87 < bbox["max_lat"]
    assert bbox["min_lon"] < 74.85 < bbox["max_lon"]


def test_known_place_is_case_insensitive() -> None:
    lower = resolve_location("mangaluru", demo_bbox=DEMO_BBOX)
    upper = resolve_location("MANGALURU", demo_bbox=DEMO_BBOX)
    assert lower["resolved_bbox"] == upper["resolved_bbox"]


def test_unrecognized_place_returns_none() -> None:
    assert resolve_location("Atlantis", demo_bbox=DEMO_BBOX) is None


def test_resolved_bbox_never_invents_coordinates_outside_demo_bbox() -> None:
    result = resolve_location("Udupi", demo_bbox=DEMO_BBOX)
    bbox = result["resolved_bbox"]
    assert bbox["min_lat"] >= DEMO_BBOX.min_lat
    assert bbox["min_lon"] >= DEMO_BBOX.min_lon
    assert bbox["max_lat"] <= DEMO_BBOX.max_lat
    assert bbox["max_lon"] <= DEMO_BBOX.max_lon
