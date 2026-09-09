import { useCallback, useEffect, useRef, useState } from "react";

import type { SupportedLanguage } from "../lib/api";

/**
 * Phase 9 — voice input via the browser's native Web Speech API
 * (`SpeechRecognition`/`webkitSpeechRecognition`). No server-side speech
 * component and no third-party STT dependency — this is a real browser
 * capability, not a stub; on a browser that doesn't implement it (Firefox,
 * most non-Chromium browsers), `supported` is `false` and the caller must
 * degrade gracefully (never claim voice input works when it structurally
 * cannot).
 *
 * Language handling: this API requires the target language to be set
 * BEFORE listening starts — it cannot auto-detect which of English/Hindi/
 * Kannada is being spoken. `SUPPORTED_LANGUAGES`'s own codes are mapped to
 * BCP-47 locale tags Chrome/Edge's recognizer accepts; "auto" is not a
 * valid recognition target, so the caller must resolve it to a concrete
 * language before calling `start()` (never silently defaulted to English
 * here — see AskOrca.tsx's own explicit language-picker requirement).
 */
const RECOGNITION_LOCALE: Record<SupportedLanguage, string> = {
  en: "en-IN",
  hi: "hi-IN",
  kn: "kn-IN",
};

// Minimal ambient shape for the non-standardized Web Speech API — no
// `@types` package ships this; declared narrowly here rather than reaching
// for `any` everywhere it's used.
interface SpeechRecognitionResultLike {
  isFinal: boolean;
  0: { transcript: string };
}
interface SpeechRecognitionEventLike extends Event {
  results: ArrayLike<SpeechRecognitionResultLike>;
  resultIndex: number;
}
interface SpeechRecognitionErrorEventLike extends Event {
  error: string;
}
interface SpeechRecognitionLike extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
}

function getRecognitionConstructor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: new () => SpeechRecognitionLike; webkitSpeechRecognition?: new () => SpeechRecognitionLike };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export type VoiceInputState = "idle" | "listening" | "processing" | "error";

export function useSpeechRecognition() {
  const [state, setState] = useState<VoiceInputState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const Constructor = getRecognitionConstructor();
  const supported = Constructor !== null;

  useEffect(() => () => recognitionRef.current?.abort(), []);

  const start = useCallback(
    (language: SupportedLanguage, onResult: (transcript: string) => void) => {
      if (!Constructor) {
        setState("error");
        setErrorMessage("Voice input is not supported in this browser. Try Chrome or Edge, or type your question instead.");
        return;
      }
      setErrorMessage(null);
      const recognition = new Constructor();
      recognition.lang = RECOGNITION_LOCALE[language];
      recognition.continuous = false;
      recognition.interimResults = false;

      recognition.onresult = (event) => {
        setState("processing");
        const transcript = Array.from(event.results as unknown as SpeechRecognitionResultLike[])
          .map((r) => r[0].transcript)
          .join(" ")
          .trim();
        if (transcript) onResult(transcript);
      };
      recognition.onerror = (event) => {
        setState("error");
        setErrorMessage(
          event.error === "not-allowed" || event.error === "permission-denied"
            ? "Microphone access was denied — allow microphone permission and try again."
            : event.error === "language-not-supported"
              ? `Voice recognition does not support this language in your browser.`
              : `Voice recognition failed (${event.error}).`,
        );
      };
      recognition.onend = () => {
        setState((current) => (current === "listening" ? "idle" : current));
      };

      recognitionRef.current = recognition;
      setState("listening");
      recognition.start();
    },
    [Constructor],
  );

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
  }, []);

  return { supported, state, errorMessage, start, stop };
}
