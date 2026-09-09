/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // ORCA coastal palette — the single source of truth for color
        // across the app. Prefer these semantic names over raw Tailwind
        // slate/cyan/black utilities everywhere except genuinely semantic
        // status colors (success/warning/error), which keep their
        // standard meaning independent of this palette.
        "orca-deep": "#183831", // deep dark teal — dark surfaces, footer, solid nav, headings-on-light
        "orca-teal": "#438C7D", // ocean teal — borders, focus rings, decorative icons (3:1 UI-component contrast is enough here)
        // A darkened variant of ocean teal used specifically wherever it is
        // the FOREGROUND of real text, or a BACKGROUND behind cream/white
        // button/message text — #438C7D only reaches ~3.6:1 against cream,
        // which fails WCAG AA for normal-size text (needs 4.5:1); #3A796C
        // reaches ~4.6:1 while still reading clearly as "ocean teal".
        "orca-teal-strong": "#3A796C",
        "orca-mint": "#86D2B3", // soft mint — secondary accents, hover states, subtle highlights
        "orca-cream": "#FFF3DF", // warm cream — primary light background, headings-on-dark

        // Deep-marine palette — everything BELOW the cinematic hero (landing
        // sections past the hero's own hand-off, plus the three dedicated
        // app pages: Ask ORCA, Route Planner, Status). Deliberately namespaced
        // "marine-*" rather than reusing "orca-deep" etc. — the hero itself
        // and its immediate chrome (Footer, mobile nav) keep the original
        // dark-teal "orca-deep" untouched; this is a second, later stop on
        // the same warm-sunset-to-deep-blue journey, not a replacement of it.
        "marine-deep": "#0A2540", // primary DARK background — navbar, footer, deliberately-dark sections
        "marine-ocean": "#0F3A5F", // secondary DARK surface — cards/panels inside a dark section
        "marine-blue": "#1E6FA8", // mid-depth accent, gradient stop
        "marine-cyan": "#38BDF8", // primary interactive accent — reads on both light and dark surfaces
        "marine-cyan-light": "#7DD3FC", // secondary highlights / icons / active states (dark-surface use only — too low-contrast for body text on white)
        "marine-white": "#F8FAFC", // primary text color ON dark-marine surfaces only
        "marine-sand": "#D4A574", // very subtle warm coastal accent — used sparingly
        "marine-success": "#10B981",
        "marine-warning": "#F59E0B",
        "marine-danger": "#EF4444",

        // Light-surface system (theme correction) — every app page and every
        // OTHER-than-deliberately-dark landing section uses these, never
        // "marine-deep"/"marine-ocean" as a full-page background. This is
        // what actually produces the light/dark RHYTHM the reference calls
        // for — before this, "marine-deep" was the only page background
        // that existed anywhere past the hero, which is the entire reason
        // the rendered app read as "dark blue everywhere."
        "marine-surface": "#FFFFFF", // card/panel background on a light section
        "marine-surface-alt": "#F5F8F7", // the light section's own PAGE background (off-white, not pure white — so white cards still read as raised)
        "marine-frost": "#D9F0F8", // light ocean-blue tint — hover states, secondary light backgrounds, subtle section banding
        "marine-mist": "#EAF8FA", // pale aqua tint — alternate light banding, very light highlight fills
        "marine-border": "#D7E6EE", // subtle light-blue border for white cards (NOT marine-cyan/15, which is calibrated for dark glass surfaces and nearly invisible on white)
        "marine-ink": "#0B2B45", // primary text/heading color ON light surfaces (dark navy — this is the "dark text on light background" half of the contrast rule)
        "marine-ink-muted": "#4B6478", // secondary/body text on light surfaces — slate-blue-gray, never marine-white/marine-cyan-light on a light background
      },
      fontFamily: {
        sans: [
          '"Space Grotesk"',
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
};
