"""ORCA Data Agents — architecture.md §10, Phase 4.

Three agents, matching the architecture's own naming exactly:

- Weather Intelligence Agent   (backend/app/agents/weather/)
- Oceanographic Intelligence Agent (backend/app/agents/oceanographic/)
- GIS & Geofencing Agent       (backend/app/agents/gis/)

These are NOT autonomous LLM agents. Per architecture.md §10's own table,
none of these three roles is an LLM call ("Real LLM agent? No" for all
three) — they are deterministic service boundaries: accept a typed
request, retrieve/validate/normalize data (reusing Phase 1's adapters and
Marine Data Fabric, never reimplementing them), apply the Temporal
Validity Gate, use a 3-tier LIVE -> CACHED -> STATIC/DEMO fallback, and
return a typed `app.models.contracts.AgentResult`. Zero LLM calls, zero
LangGraph, zero natural-language generation anywhere in this package.
"""
