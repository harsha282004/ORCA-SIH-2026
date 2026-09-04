# ORCA-SIH-2026

## Marine EcOsystem Reasoning with Collaborative Agents

ORCA is an **agentic AI-based conversational marine-intelligence platform** designed to help users understand marine and coastal conditions through natural-language queries.

The system combines **weather and oceanographic data, geospatial intelligence, deterministic risk analysis, fishing suitability analysis, evidence-backed reasoning, and risk-aware routing** into a unified conversational platform.

> **Core Principle:**  
> LLM interprets and explains → deterministic code computes and enforces safety → evidence supports every claim → human makes the final decision.

---

## 🎯 Problem Statement

Marine decision-making often requires information from multiple sources such as:

- Weather conditions
- Oceanographic conditions
- Marine hazards
- Coastal and marine boundaries
- Protected and restricted areas
- Fishing suitability information
- Spatial and temporal constraints

These sources are often disconnected, making it difficult for users to obtain a unified understanding of marine conditions.

ORCA addresses this problem through a conversational AI system that integrates these sources and provides **context-aware, evidence-backed and safety-aware marine intelligence**.

---

## 🚀 Proposed Solution

ORCA uses a **collaborative multi-agent architecture** orchestrated using **LangGraph**.

The architecture separates language understanding and explanation from deterministic computation and safety enforcement.

### High-Level Architecture

```text
                         USER
                          │
                          ▼
              ┌─────────────────────┐
              │ Query Understanding │
              │       Agent         │
              └──────────┬──────────┘
                         │
                         ▼
                 ┌───────────────┐
                 │   LangGraph   │
                 │ Orchestration │
                 └───────┬───────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   Weather Agent   Oceanographic     GIS &
                      Agent         Geofencing
        │                │                │
        └────────────────┼────────────────┘
                         │
                         ▼
               Risk & Suitability
                       Agent
                         │
                 ┌───────┴───────┐
                 │ Route Agent   │
                 │  (Conditional)│
                 └───────┬───────┘
                         │
                         ▼
              Evidence & Provenance
                         │
                         ▼
                 Safety Guard
                         │
                         ▼
                 Decision Engine
                         │
                         ▼
              Evidence & Explanation

## 🌊 What Does ORCA Actually Do?

ORCA is a **conversational marine-intelligence system**.

Instead of requiring a user to manually check weather APIs, ocean conditions, marine boundaries, risk information and routing tools separately, ORCA allows the user to ask questions in natural language.

The system understands the request, collects the relevant marine information, performs deterministic spatial and risk analysis, checks safety constraints, and provides an evidence-backed response.

### Example

A user could ask:

> "Is it safe to go fishing near Mangaluru tomorrow morning?"

ORCA processes the request through multiple components:

```text
User Question
     │
     ▼
Understand:
"What does the user want?"
     │
     ▼
Identify:
Location → Mangaluru
Activity → Fishing
Time → Tomorrow morning
     │
     ▼
Collect Marine Information
     │
     ├── Weather
     ├── Waves
     ├── Wind
     ├── Ocean conditions
     ├── Marine hazards
     └── Geospatial restrictions
     │
     ▼
Analyze
     │
     ├── Fishing suitability
     ├── Marine risk
     ├── Data freshness
     ├── Data confidence
     └── Restricted areas
     │
     ▼
Safety Guard
     │
     ├── Safe
     ├── Caution
     └── Block / No safe recommendation
     │
     ▼
Evidence-backed Explanation
     │
     ▼
User receives the result

                         │
                         ▼
                   USER RESPONSE
