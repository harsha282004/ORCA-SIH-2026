import { useEffect, useRef, useState, type FormEvent } from "react";
import { Mic, Send, Square, Volume2 } from "lucide-react";

import {
  askOrca,
  postVoiceSpeak,
  ApiRequestError,
  SUPPORTED_LANGUAGES,
  type Decision,
  type SafetyGuardResult,
  type QueryResponseData,
  type SupportedLanguage,
} from "../../lib/api";
import { ComparisonBarChart } from "../charts/ComparisonBarChart";
import { LineSeriesChart, type ChartSeries } from "../charts/LineSeriesChart";
import { EvidenceList, type EvidenceRow } from "../evidence/Evidence";
import { useSpeechRecognition } from "../../hooks/useSpeechRecognition";

interface ChatTurn {
  id: string;
  role: "user" | "orca" | "error";
  text: string;
  decision?: Decision | null;
  safety?: SafetyGuardResult | null;
  language?: string;
  reused?: boolean;
  data?: QueryResponseData | null;
  // Phase 8 — the same `Evidence[]`/`confidence` architecture.md §12 already
  // defines on every `QueryApiResponse`, now actually rendered (task §5's
  // "make evidence/provenance consistently visible") rather than discarded.
  evidence?: Record<string, unknown>[] | null;
}

const LANGUAGE_LABEL: Record<string, string> = { en: "EN", hi: "हिन्दी", kn: "ಕನ್ನಡ" };

// Semantic status colors keep their standard meaning independent of the
// marine palette, tuned for legibility on a deep-ocean glass surface.
const DECISION_BADGE_STYLES: Record<string, string> = {
  RECOMMEND: "border-marine-success/40 bg-marine-success/15 text-marine-success",
  RECOMMEND_WITH_CAUTION: "border-marine-warning/40 bg-marine-warning/15 text-marine-warning",
  PROVIDE_ALTERNATIVES: "border-marine-warning/40 bg-marine-warning/15 text-marine-warning",
  NO_SAFE_RECOMMENDATION: "border-marine-danger/40 bg-marine-danger/15 text-marine-danger",
};

// A deliberately small set of examples across all three tested languages
// (task §4's own priority order) — never presented as an exhaustive list
// of what ORCA "supports," just a starting point.
const EXAMPLE_QUERIES = [
  "Is it safe to go fishing near Mangaluru tomorrow morning?",
  "What if wave height increases to 3.5 metres?",
  "When is the best time to fish tomorrow?",
  "ಮಂಗಳೂರಿನ ಹತ್ತಿರ ಮೀನುಗಾರಿಕೆಗೆ ಸೂಕ್ತವಾದ ಸ್ಥಳ ಹುಡುಕಿ",
  "मंगलुरु के पास सुरक्षित मछली पकड़ने की जगह खोजो",
];

let turnCounter = 0;
function nextTurnId(): string {
  turnCounter += 1;
  return `turn-${turnCounter}`;
}

/** A compact deterministic-result card — every value here is read directly
 * off the backend response (`app.api.v1.query`'s own `data` object), never
 * computed or paraphrased in this component (task §20's "evidence remains
 * attached"). Renders nothing when the turn carries no structured result
 * worth summarizing (a clarification, a plain point-safety explanation
 * with nothing beyond decision/safety already shown as badges above).
 */
function ResultCard({ data, evidence }: { data?: QueryResponseData | null; evidence?: Record<string, unknown>[] | null }) {
  if (!data) return null;
  const top = data.fishing_candidates?.top as
    | { latitude?: number; longitude?: number; suitability_category?: string; risk_level?: string; distance_km?: number }
    | undefined;
  const route = data.route;
  const scenario = data.scenario;
  const temporal = data.temporal;

  if (!top && !route && !data.marine_safety && !scenario && !temporal) return null;

  // Every field read below is a literal key on architecture.md §12's
  // `Evidence` object as returned by the backend — nothing computed here.
  const evidenceRows: EvidenceRow[] = (evidence ?? []).map((e) => ({
    source: String(e.source ?? "unknown"),
    variable: String(e.parameter ?? "value").replaceAll("_", " "),
    value: e.value != null ? `${e.value}${e.unit ? ` ${e.unit}` : ""}` : "n/a",
    timestamp: typeof e.timestamp === "string" ? e.timestamp : null,
    confidence: typeof e.confidence === "number" ? e.confidence : null,
    // `source_tier` here is architecture.md §12's live/cached/static/
    // reference/synthetic vocabulary — a different axis than the map
    // layers' classify_freshness_status labels FreshnessBadge renders, so
    // it is shown as plain coverage text rather than forced through that
    // badge's narrower color mapping (which would mis-color it).
    coverage: typeof e.source_tier === "string" ? `source tier: ${e.source_tier}` : null,
  }));

  return (
    <div className="mt-2 space-y-1.5 rounded-lg border border-marine-cyan/10 bg-marine-deep/40 px-3 py-2 text-[11px] text-marine-white/70">
      {top && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-semibold text-marine-white/90">Recommended Area</span>
          {top.suitability_category && <span>Suitability: {top.suitability_category}</span>}
          {top.risk_level && <span>Risk: {top.risk_level}</span>}
          {typeof top.latitude === "number" && typeof top.longitude === "number" && (
            <span>
              {top.latitude.toFixed(3)}, {top.longitude.toFixed(3)}
            </span>
          )}
        </div>
      )}
      {route && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-semibold text-marine-white/90">Route {(route as { label?: string }).label ?? ""}</span>
          <span>{route.metrics.total_distance_km.toFixed(1)} km</span>
          <span>Risk: {(route as { risk_level?: string }).risk_level ?? "—"}</span>
          {data.route_comparison?.recommended_label && <span>ORCA pick: Route {data.route_comparison.recommended_label}</span>}
        </div>
      )}
      {data.marine_safety && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-semibold text-marine-white/90">Marine Safety: {data.marine_safety.level}</span>
          <span>
            {data.marine_safety.hazards.length === 0
              ? "No relevant hazards detected from available data."
              : `${data.marine_safety.hazards.length} hazard(s) detected`}
          </span>
        </div>
      )}
      {scenario && (
        <div className="space-y-2 rounded border border-marine-warning/20 bg-marine-warning/5 px-2 py-2">
          <p className="font-semibold uppercase tracking-wide text-marine-warning">{scenario.label}</p>
          <ComparisonBarChart
            height={140}
            groups={[
              { key: "baseline", label: "Baseline", value: scenario.baseline_value, unit: scenario.unit, color: "#38BDF8", sublabel: scenario.baseline.decision.outcome.replaceAll("_", " ") },
              { key: "scenario", label: "Scenario", value: scenario.scenario_value, unit: scenario.unit, color: "#F59E0B", sublabel: scenario.scenario_result.decision.outcome.replaceAll("_", " ") },
            ]}
          />
          <p className="italic text-marine-white/50">{scenario.assumption}</p>
          {scenario.scope_note && <p className="italic text-marine-white/40">{scenario.scope_note}</p>}
        </div>
      )}
      {temporal && (
        <div className="space-y-1">
          <span className="font-semibold text-marine-white/90">
            Best time: {temporal.best_time_index !== null ? new Date(temporal.series[temporal.best_time_index].timestamp).toLocaleString() : "none within this window"}
          </span>
          <LineSeriesChart
            height={160}
            highlightIndex={temporal.best_time_index}
            series={
              [
                { key: "wave", label: "Wave Height", color: "#38BDF8", unit: "m", points: temporal.series.map((s) => ({ timestamp: s.timestamp, value: s.environmental_context?.wave_height_m ?? null })) },
                { key: "wind", label: "Wind Speed", color: "#F59E0B", unit: "m/s", points: temporal.series.map((s) => ({ timestamp: s.timestamp, value: s.environmental_context?.wind_speed_ms ?? null })) },
              ] as ChartSeries[]
            }
          />
        </div>
      )}
      {evidenceRows.length > 0 && <EvidenceList title="Evidence" rows={evidenceRows} />}
    </div>
  );
}

export function AskOrca() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  // Phase 6 (task §32) — "auto" (the default) never sends language_override
  // at all; automatic detection is the default everywhere, never something
  // the user must configure before asking a question.
  const [languageChoice, setLanguageChoice] = useState<"auto" | SupportedLanguage>("auto");

  // --- Phase 9: voice output (ElevenLabs TTS via the backend) -------------
  // One <audio> element, one turn "speaking" at a time — starting a new
  // playback stops whatever was already playing, matching the task's own
  // "Stop audio button when playing" / single active-voice UX.
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [speakingTurnId, setSpeakingTurnId] = useState<string | null>(null);
  const [voiceLoadingTurnId, setVoiceLoadingTurnId] = useState<string | null>(null);
  const [voiceErrorByTurn, setVoiceErrorByTurn] = useState<Record<string, string>>({});

  useEffect(() => {
    const audio = new Audio();
    audioRef.current = audio;
    const onEnded = () => setSpeakingTurnId(null);
    audio.addEventListener("ended", onEnded);
    return () => {
      audio.removeEventListener("ended", onEnded);
      audio.pause();
    };
  }, []);

  const stopSpeaking = () => {
    audioRef.current?.pause();
    setSpeakingTurnId(null);
  };

  const playTurn = async (turn: ChatTurn) => {
    if (speakingTurnId === turn.id) {
      stopSpeaking();
      return;
    }
    stopSpeaking();
    setVoiceLoadingTurnId(turn.id);
    setVoiceErrorByTurn((prev) => {
      const next = { ...prev };
      delete next[turn.id];
      return next;
    });
    const result = await postVoiceSpeak(turn.text, (turn.language as SupportedLanguage) ?? "en");
    setVoiceLoadingTurnId(null);
    if (result.kind === "unavailable") {
      setVoiceErrorByTurn((prev) => ({ ...prev, [turn.id]: result.reason }));
      return;
    }
    if (audioRef.current) {
      audioRef.current.src = result.audioUrl;
      void audioRef.current.play();
      setSpeakingTurnId(turn.id);
    }
  };

  // --- Phase 9: voice input (browser Web Speech API) -----------------------
  const speech = useSpeechRecognition();
  const voiceInputLanguage = languageChoice === "auto" ? null : languageChoice;

  const startListening = () => {
    if (!voiceInputLanguage) return; // guarded by the disabled mic button below
    speech.start(voiceInputLanguage, (transcript) => {
      setInput(transcript);
      void submitQuery(transcript);
    });
  };

  const submitQuery = async (query: string) => {
    const trimmed = query.trim();
    if (!trimmed || loading) return;

    setTurns((prev) => [...prev, { id: nextTurnId(), role: "user", text: trimmed }]);
    setInput("");
    setLoading(true);

    try {
      const response = await askOrca({
        query: trimmed,
        session_id: sessionId,
        language_override: languageChoice === "auto" ? undefined : languageChoice,
      });
      setSessionId(response.session_id);

      if (response.data?.status === "clarification_needed" && response.data.clarification) {
        setTurns((prev) => [
          ...prev,
          { id: nextTurnId(), role: "orca", text: response.data!.clarification!.reason, language: response.data!.language },
        ]);
      } else if (response.data) {
        setTurns((prev) => [
          ...prev,
          {
            id: nextTurnId(),
            role: "orca",
            text: response.data!.explanation ?? "ORCA processed the query but returned no explanation text.",
            decision: response.data!.decision,
            safety: response.data!.safety,
            language: response.data!.language,
            reused: response.data!.reused_prior_result,
            data: response.data,
            evidence: response.evidence,
          },
        ]);
      } else {
        const message = response.errors?.[0]?.message ?? "ORCA could not process this query.";
        setTurns((prev) => [...prev, { id: nextTurnId(), role: "error", text: message }]);
      }
    } catch (err) {
      const message = err instanceof ApiRequestError ? err.message : "Something went wrong while contacting ORCA.";
      setTurns((prev) => [...prev, { id: nextTurnId(), role: "error", text: message }]);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    void submitQuery(input);
  };

  // A single, honest status pill for the whole widget — Ready/Listening/
  // Processing/Speaking (task §"Voice UX" states), never more than one
  // active at a time since voice input and output are mutually exclusive
  // actions here.
  const voiceStatus: { label: string; dot: string } =
    speech.state === "listening"
      ? { label: "Listening…", dot: "bg-marine-danger animate-pulse" }
      : speech.state === "processing"
        ? { label: "Processing…", dot: "bg-marine-warning animate-pulse" }
        : speakingTurnId
          ? { label: "Speaking…", dot: "bg-marine-cyan animate-pulse" }
          : loading
            ? { label: "Thinking…", dot: "bg-marine-cyan animate-pulse" }
            : { label: "Ready", dot: "bg-marine-success" };

  return (
    <div>
      <div className="overflow-hidden rounded-2xl border border-marine-cyan/15 bg-marine-deep/60 shadow-sm backdrop-blur-sm">
      {/* --- CHAT HEADER ---------------------------------------------------- */}
      <div className="flex items-center justify-between border-b border-marine-cyan/10 px-5 py-3 sm:px-6">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-marine-cyan/15 text-sm font-semibold text-marine-cyan-light">O</span>
          <span className="text-sm font-semibold text-marine-white">ORCA Assistant</span>
        </div>
        <span className="flex items-center gap-1.5 text-xs font-medium text-marine-white/60">
          <span className={`h-2 w-2 rounded-full ${voiceStatus.dot}`} aria-hidden="true" />
          {voiceStatus.label}
        </span>
      </div>

      {/* --- MESSAGE AREA ---------------------------------------------------- */}
      <div className="max-h-[28rem] space-y-4 overflow-y-auto p-5 sm:p-6" role="log" aria-live="polite">
        {turns.length === 0 && (
          <p className="text-sm text-marine-white/50">No messages yet — try one of the examples below, or use the microphone.</p>
        )}
        {turns.map((turn) => (
          <div key={turn.id} className={turn.role === "user" ? "flex justify-end" : "flex justify-start"}>
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                turn.role === "user"
                  ? "bg-marine-cyan text-marine-deep"
                  : turn.role === "error"
                    ? "border border-marine-danger/40 bg-marine-danger/10 text-marine-white"
                    : "border border-marine-cyan/15 bg-marine-ocean/50 text-marine-white"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <p>{turn.text}</p>
                {turn.role === "orca" && (
                  <button
                    type="button"
                    onClick={() => void playTurn(turn)}
                    disabled={voiceLoadingTurnId === turn.id}
                    title={speakingTurnId === turn.id ? "Stop" : "Play ORCA's voice response"}
                    aria-label={speakingTurnId === turn.id ? "Stop voice playback" : "Play voice response"}
                    className="mt-0.5 shrink-0 rounded-full p-1.5 text-marine-cyan-light transition-colors hover:bg-marine-cyan/15 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-marine-cyan"
                  >
                    {voiceLoadingTurnId === turn.id ? (
                      <span className="block h-3.5 w-3.5 animate-spin rounded-full border-2 border-marine-cyan-light border-t-transparent" />
                    ) : speakingTurnId === turn.id ? (
                      <Square size={14} />
                    ) : (
                      <Volume2 size={14} />
                    )}
                  </button>
                )}
              </div>
              {voiceErrorByTurn[turn.id] && <p className="mt-1.5 text-xs italic text-marine-white/40">Voice output unavailable: {voiceErrorByTurn[turn.id]}</p>}
              {(turn.decision || turn.safety || turn.language) && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {turn.role === "orca" && turn.language && (
                    <span
                      className="rounded-full border border-marine-cyan/25 bg-marine-cyan/5 px-2 py-0.5 text-[11px] font-medium text-marine-cyan-light"
                      title="Detected/response language"
                    >
                      {LANGUAGE_LABEL[turn.language] ?? turn.language.toUpperCase()}
                    </span>
                  )}
                  {turn.decision && (
                    <span
                      className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${
                        DECISION_BADGE_STYLES[turn.decision.outcome] ?? "border-marine-cyan/20 bg-marine-cyan/5 text-marine-white"
                      }`}
                    >
                      {turn.decision.outcome.replaceAll("_", " ")}
                    </span>
                  )}
                  {turn.safety && turn.safety.outcome !== "PASS" && (
                    <span className="rounded-full border border-marine-cyan/20 bg-marine-cyan/5 px-2 py-0.5 text-[11px] font-medium text-marine-white">
                      {turn.safety.outcome.replaceAll("_", " ")}
                    </span>
                  )}
                  {turn.reused && (
                    <span
                      className="rounded-full border border-marine-white/15 bg-marine-white/5 px-2 py-0.5 text-[11px] font-medium text-marine-white/60"
                      title="Answered from an already-computed result — no new deterministic evaluation was needed"
                    >
                      from earlier result
                    </span>
                  )}
                </div>
              )}
              <ResultCard data={turn.data} evidence={turn.evidence} />
            </div>
          </div>
        ))}
        {loading && <p className="text-sm text-marine-white/50">ORCA is thinking…</p>}
      </div>

      {/* --- INPUT AREA ------------------------------------------------------ */}
      <div className="border-t border-marine-cyan/10 bg-marine-deep/40 p-4 sm:p-5">
        {speech.errorMessage && <p className="mb-2 text-xs italic text-marine-warning">{speech.errorMessage}</p>}
        <form onSubmit={handleSubmit} className="flex items-center gap-2">
          <label htmlFor="ask-orca-input" className="sr-only">
            Ask ORCA a question
          </label>
          <input
            id="ask-orca-input"
            type="text"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Ask ORCA about the ocean… (English, ಕನ್ನಡ, or हिन्दी)"
            className="flex-1 rounded-full border border-marine-cyan/25 bg-marine-deep/60 px-4 py-2.5 text-sm text-marine-white placeholder:text-marine-white/40 focus:border-marine-cyan focus:outline-none focus-visible:ring-2 focus-visible:ring-marine-cyan"
          />
          <button
            type="button"
            onClick={() => (speech.state === "listening" ? speech.stop() : startListening())}
            disabled={!speech.supported || !voiceInputLanguage}
            title={
              !speech.supported
                ? "Voice input is not supported in this browser"
                : !voiceInputLanguage
                  ? "Choose a response language below before using voice input"
                  : speech.state === "listening"
                    ? "Stop listening"
                    : "Speak your question"
            }
            aria-label="Voice input"
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-marine-cyan ${
              speech.state === "listening"
                ? "border-marine-danger bg-marine-danger/20 text-marine-danger"
                : "border-marine-cyan/25 text-marine-cyan-light hover:border-marine-cyan hover:bg-marine-cyan/10"
            } disabled:cursor-not-allowed disabled:opacity-40`}
          >
            <Mic size={16} />
          </button>
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="flex items-center gap-2 rounded-full bg-marine-cyan px-5 py-2.5 text-sm font-semibold text-marine-deep transition-colors hover:bg-marine-cyan-light disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Send size={14} />
            <span className="hidden sm:inline">Ask ORCA</span>
          </button>
        </form>
      </div>
      </div>

      {/* --- QUICK PROMPTS + LANGUAGE PICKER --------------------------------
          Deliberately outside the chat card itself (task's own chat-header/
          message-area/input-area structure is for the conversation surface;
          these are page-level quick actions, not chat content). */}
      <div className="mt-4 space-y-3">
        <div className="flex flex-wrap gap-2">
          {EXAMPLE_QUERIES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => void submitQuery(example)}
              disabled={loading}
              className="rounded-full border border-marine-cyan/25 px-3 py-1 text-xs text-marine-white/70 transition-colors hover:border-marine-cyan hover:bg-marine-cyan/10 hover:text-marine-white disabled:opacity-50"
            >
              {example}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="ask-orca-language" className="text-xs text-marine-white/50">
            Response &amp; voice language
          </label>
          <select
            id="ask-orca-language"
            value={languageChoice}
            onChange={(event) => setLanguageChoice(event.target.value as "auto" | SupportedLanguage)}
            className="rounded-full border border-marine-cyan/25 bg-marine-deep/60 px-3 py-1 text-xs text-marine-white focus:border-marine-cyan focus:outline-none"
          >
            <option value="auto">Auto (detect from query)</option>
            {SUPPORTED_LANGUAGES.map((lang) => (
              <option key={lang.code} value={lang.code}>
                {lang.label}
              </option>
            ))}
          </select>
          <span className="text-xs text-marine-white/30">Voice input needs a specific language selected here.</span>
        </div>
      </div>
    </div>
  );
}
