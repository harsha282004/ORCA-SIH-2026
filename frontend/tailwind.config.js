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
        "marine-deep": "#0A2540", // primary background — deep ocean
        "marine-ocean": "#0F3A5F", // secondary surfaces / sections
        "marine-blue": "#1E6FA8", // mid-depth accent, gradient stop
        "marine-cyan": "#38BDF8", // primary interactive accent
        "marine-cyan-light": "#7DD3FC", // secondary highlights / icons / active states
        "marine-white": "#F8FAFC", // primary text on deep-marine surfaces
        "marine-sand": "#D4A574", // very subtle warm coastal accent — used sparingly
        "marine-success": "#10B981",
        "marine-warning": "#F59E0B",
        "marine-danger": "#EF4444",
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
