import { X } from "lucide-react";

import type { SelectedFeature } from "./mapLayers";
import { FreshnessBadge } from "./FreshnessBadge";

interface EvidencePanelProps {
  feature: SelectedFeature | null;
  onClose: () => void;
}

function Field({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex justify-between gap-3 py-0.5">
      <dt className="text-marine-ink-muted">{label}</dt>
      <dd className="text-right text-marine-ink">{value}</dd>
    </div>
  );
}

const LAYER_TITLES: Record<string, string> = {
  "risk-surface": "ORCA Risk",
  geofences: "Restricted Zone",
  suitability: "ORCA Fishing Suitability",
  sst: "Sea Surface Temperature",
  waves: "Wave Conditions",
  currents: "Ocean Current",
  route: "Route Segment",
  bathymetry: "GEBCO Bathymetry — Reference",
  chlorophyll: "INCOIS Chlorophyll-a",
  "incois-sst": "INCOIS Sea Surface Temperature",
  wind: "Wind",
  "fishing-candidate": "ORCA Fishing Candidate",
  hazard: "Marine Hazard",
  "route-option": "Route Option",
};

/**
 * The clickable-feature evidence panel — every value rendered here is read
 * directly off the backend's own GeoJSON feature properties (app/api/v1/
 * layers.py, app/api/v1/route.py). Nothing is computed or invented here.
 */
export function EvidencePanel({ feature, onClose }: EvidencePanelProps) {
  if (!feature) return null;
  const p = feature.properties;

  return (
    <div className="pointer-events-auto w-80 max-w-[90vw] rounded-xl border border-marine-border bg-marine-surface p-4 text-sm text-marine-ink shadow-xl">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-marine-blue">
          {LAYER_TITLES[feature.layer] ?? feature.layer}
        </h3>
        <button type="button" onClick={onClose} aria-label="Close evidence panel" className="text-marine-ink-muted hover:text-marine-ink">
          <X size={16} />
        </button>
      </div>

      {typeof p.status === "string" && (
        <div className="mb-2">
          <FreshnessBadge status={p.status as string} />
        </div>
      )}

      {feature.layer === "risk-surface" && (
        <dl className="text-xs">
          <Field label="Navigable" value={p.navigable ? "Yes" : "No"} />
          {p.navigable ? (
            <>
              <Field label="Risk level" value={p.risk_level as string} />
              <Field label="Risk score" value={typeof p.risk_score === "number" ? p.risk_score.toFixed(3) : null} />
              <Field label="Hazard score" value={typeof p.hazard_score === "number" ? p.hazard_score.toFixed(3) : null} />
              <Field label="Geofence penalty" value={typeof p.geofence_soft_penalty === "number" ? p.geofence_soft_penalty.toFixed(3) : null} />
            </>
          ) : (
            <Field label="Block reason" value={p.block_reason as string} />
          )}
        </dl>
      )}

      {feature.layer === "geofences" && (
        <dl className="text-xs">
          <Field label="Name" value={p.name as string} />
          <Field label="Category" value={p.category as string} />
          <Field label="Authoritative" value={p.is_authoritative ? "Yes — official boundary" : "No — illustrative/demo only"} />
          <Field label="Active now" value={p.active_now ? "Yes" : "No"} />
          <Field label="Source" value={p.source as string} />
        </dl>
      )}

      {feature.layer === "suitability" && (
        <dl className="text-xs">
          <Field label="Suitability" value={p.category as string} />
          <Field label="Score" value={typeof p.score === "number" ? p.score.toFixed(3) : null} />
          <Field label="Risk" value={p.risk_level as string} />
          <Field label="Confidence" value={typeof p.confidence === "number" ? `${(p.confidence * 100).toFixed(0)}%` : null} />
          <Field label="PFZ reference" value={p.pfz_reference_status === "unavailable" ? "Not available" : (p.pfz_reference_status as string)} />
          {p.components && typeof p.components === "object" ? (
            <>
              <p className="mt-2 text-marine-ink-muted">Supporting factors</p>
              {Object.entries(p.components as Record<string, number>).map(([k, v]) => (
                <Field key={k} label={k.replaceAll("_", " ")} value={v.toFixed(3)} />
              ))}
            </>
          ) : null}
          <p className="mt-2 text-[10px] italic text-marine-ink-muted/70">{p.disclaimer as string}</p>
        </dl>
      )}

      {feature.layer === "sst" && (
        <dl className="text-xs">
          <Field label="Temperature" value={typeof p.sea_surface_temperature_c === "number" ? `${p.sea_surface_temperature_c.toFixed(1)} °C` : null} />
          <Field label="Valid from" value={p.valid_from as string} />
          <Field label="Valid to" value={p.valid_to as string} />
          <Field label="Retrieved" value={p.retrieved_at as string} />
          <Field label="Source" value={p.source as string} />
          <Field label="Confidence" value={typeof p.confidence === "number" ? `${(p.confidence * 100).toFixed(0)}%` : null} />
        </dl>
      )}

      {feature.layer === "waves" && (
        <dl className="text-xs">
          <Field label="Wave height" value={typeof p.wave_height_m === "number" ? `${p.wave_height_m.toFixed(2)} m` : null} />
          <Field label="Wave period" value={typeof p.wave_period_s === "number" ? `${p.wave_period_s.toFixed(1)} s` : null} />
          <Field label="Wave direction" value={typeof p.wave_direction_deg === "number" ? `${p.wave_direction_deg.toFixed(0)}°` : null} />
          <Field label="Retrieved" value={p.retrieved_at as string} />
          <Field label="Source" value={p.source as string} />
        </dl>
      )}

      {feature.layer === "currents" && (
        <dl className="text-xs">
          <Field label="Speed" value={typeof p.ocean_current_velocity_ms === "number" ? `${p.ocean_current_velocity_ms.toFixed(2)} m/s` : null} />
          <Field label="Direction" value={typeof p.ocean_current_direction_deg === "number" ? `${p.ocean_current_direction_deg.toFixed(0)}°` : null} />
          <Field label="Retrieved" value={p.retrieved_at as string} />
          <Field label="Source" value={p.source as string} />
        </dl>
      )}

      {feature.layer === "bathymetry" && (
        <dl className="text-xs">
          <Field label="Depth" value={typeof p.depth_m === "number" ? `${Math.abs(p.depth_m).toFixed(0)} m ${p.depth_m < 0 ? "below sea level" : "(land)"}` : "no data"} />
          <Field label="TID code" value={typeof p.tid === "number" ? p.tid : null} />
          <p className="mt-2 text-[10px] italic text-marine-ink-muted/70">
            GEBCO_2026 Grid — reference/supporting geospatial data, not a live navigation or safety guarantee.
          </p>
        </dl>
      )}

      {feature.layer === "chlorophyll" && (
        <dl className="text-xs">
          <Field label="Concentration" value={typeof p.value === "number" ? `${p.value.toFixed(3)} ${(p.unit as string) ?? "mg/m^3"}` : "no data"} />
          <p className="mt-2 text-[10px] italic text-marine-ink-muted/70">
            INCOIS chlorophyll-a concentration — an environmental input to fishing suitability, not a measure of fish abundance.
          </p>
        </dl>
      )}

      {feature.layer === "incois-sst" && (
        <dl className="text-xs">
          <Field label="Temperature" value={typeof p.value === "number" ? `${p.value.toFixed(2)} ${(p.unit as string) ?? "degC"}` : "no data"} />
          <p className="mt-2 text-[10px] italic text-marine-ink-muted/70">
            A sparse, acquired INCOIS sample (56 points region-wide) — distinct from the live, denser Open-Meteo SST layer. Not a continuous field.
          </p>
        </dl>
      )}

      {feature.layer === "wind" && (
        <dl className="text-xs">
          <Field label="Speed" value={typeof p.wind_speed_ms === "number" ? `${p.wind_speed_ms.toFixed(2)} m/s` : null} />
          <Field label="Direction" value={typeof p.wind_direction_deg === "number" ? `${p.wind_direction_deg.toFixed(0)}°` : null} />
          <Field label="Retrieved" value={p.retrieved_at as string} />
          <Field label="Source" value="open-meteo-weather" />
        </dl>
      )}

      {feature.layer === "fishing-candidate" && (
        <dl className="text-xs">
          <Field label="Status" value={(p.status as string)?.replaceAll("_", " ")} />
          {p.rank ? <Field label="Rank" value={`#${p.rank}`} /> : null}
          <Field label="Suitability" value={p.suitability_category as string} />
          <Field label="Suitability score" value={typeof p.suitability_score === "number" ? p.suitability_score.toFixed(3) : null} />
          <Field label="Risk" value={p.risk_level as string} />
          <Field label="Risk score" value={typeof p.risk_score === "number" ? p.risk_score.toFixed(3) : null} />
          <Field label="Safety" value={p.safety_outcome as string} />
          <Field label="Decision" value={(p.decision_outcome as string)?.replaceAll("_", " ")} />
          <Field label="Confidence" value={typeof p.confidence === "number" ? `${(p.confidence * 100).toFixed(0)}%` : null} />
          <Field label="Distance" value={typeof p.distance_km === "number" ? `${p.distance_km.toFixed(1)} km` : null} />
          {p.reason ? <p className="mt-2 text-marine-warning">{p.reason as string}</p> : null}
          {p.environmental_context && typeof p.environmental_context === "object" ? (
            <>
              <p className="mt-2 text-marine-ink-muted">Environmental context (informational — SST is not a suitability input)</p>
              {Object.entries(p.environmental_context as Record<string, number | null>)
                .filter(([, v]) => v != null)
                .map(([k, v]) => (
                  <Field key={k} label={k.replaceAll("_", " ")} value={(v as number).toFixed(2)} />
                ))}
            </>
          ) : null}
          {Array.isArray(p.risk_factors) && p.risk_factors.length > 0 ? (
            <>
              <p className="mt-2 text-marine-ink-muted">Real risk factors (from ORCA Risk Engine)</p>
              {(p.risk_factors as Array<{ name: string; contribution: number }>).map((f) => (
                <Field key={f.name} label={f.name.replaceAll("_", " ")} value={f.contribution.toFixed(3)} />
              ))}
            </>
          ) : null}
          {p.active_hazards_checked && Array.isArray(p.active_hazards) ? (
            <>
              <p className="mt-2 text-marine-ink-muted">Marine hazards considered (Phase 4)</p>
              {(p.active_hazards as Array<{ hazard_type: string; severity: string }>).length === 0 ? (
                <p className="text-marine-success">No active hazard detected for this candidate.</p>
              ) : (
                (p.active_hazards as Array<{ hazard_type: string; severity: string }>).map((h, i) => (
                  <Field key={i} label={h.hazard_type.replaceAll("_", " ")} value={h.severity} />
                ))
              )}
            </>
          ) : null}
          <p className="mt-2 text-[10px] italic text-marine-ink-muted/70">
            ORCA Fishing Suitability decision support — not fish detection, not a guaranteed catch.
          </p>
        </dl>
      )}

      {feature.layer === "hazard" && (
        <dl className="text-xs">
          <Field label="Type" value={(p.hazard_type as string)?.replaceAll("_", " ")} />
          <Field label="Severity" value={p.severity as string} />
          <Field label="Title" value={p.title as string} />
          <Field label="Distance" value={typeof p.distance_km === "number" ? `${p.distance_km.toFixed(1)} km` : null} />
          <Field label="Authoritative" value={p.is_authoritative ? "Yes" : p.is_proxy ? "No — model-derived proxy" : "No"} />
          <Field label="Freshness" value={p.freshness as string} />
          <Field label="Observed" value={p.observed_at as string} />
          <Field label="Valid until" value={p.valid_until as string} />
          <Field label="Source" value={p.source as string} />
          {p.description ? <p className="mt-2 leading-relaxed text-marine-ink-muted">{p.description as string}</p> : null}
        </dl>
      )}

      {feature.layer === "route" && (
        <dl className="text-xs">
          <Field label="Cell" value={p.cell_id as string} />
          <Field label="Risk score" value={typeof p.risk_score === "number" ? p.risk_score.toFixed(3) : "n/a"} />
          <Field label="Hazard score" value={typeof p.hazard_score === "number" ? p.hazard_score.toFixed(3) : "n/a"} />
          <Field label="Geofence penalty" value={typeof p.geofence_soft_penalty === "number" ? p.geofence_soft_penalty.toFixed(3) : null} />
        </dl>
      )}

      {feature.layer === "route-option" && (
        <dl className="text-xs">
          <Field label="Route" value={`Route ${p.label as string}`} />
          <Field
            label="Distance"
            value={
              typeof p.metrics === "object" && p.metrics && typeof (p.metrics as Record<string, unknown>).total_distance_km === "number"
                ? `${((p.metrics as Record<string, unknown>).total_distance_km as number).toFixed(1)} km`
                : null
            }
          />
          <Field label="Risk" value={p.risk_level as string} />
          <Field label="Safety" value={(p.safety as { outcome?: string } | undefined)?.outcome} />
          <Field label="Decision" value={(p.decision as { outcome?: string } | undefined)?.outcome?.replaceAll("_", " ")} />
          <Field
            label="Hazards near route"
            value={Array.isArray(p.hazards_near_route) ? `${p.hazards_near_route.length} detected` : "0 detected"}
          />
          <p className="mt-2 text-[10px] italic text-marine-ink-muted/70">Click "Select" in the Route Options list to make this the active route.</p>
        </dl>
      )}
    </div>
  );
}
