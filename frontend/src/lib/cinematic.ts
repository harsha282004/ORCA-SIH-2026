// Shared constants for the frame-sequence cinematic hero — kept in one
// place so the scroll engine (CinematicHero), the frame renderer
// (CinematicFrameSequence), and anything reacting to "has the hero
// finished" (Navbar) never drift out of sync with independently guessed
// numbers.

// The cinematic section's total scroll distance — tuned so the full
// 1,200-frame sequence can be appreciated without an excessive scroll
// distance. Configurable here; 300vh sits in the middle of the 250-350vh
// range found to work well.
export const CINEMATIC_SCROLL_HEIGHT_VH = 300;

// Once overall cinematic progress (0..1) crosses this fraction, the
// hand-off-to-content transition (dimming + bottom fade) begins, finishing
// at progress = 1.
export const CINEMATIC_TRANSITION_START = 0.88;

// The authoritative frame count for /public/cinematics/frames/ — exactly
// frame-0001.jpg through frame-1200.jpg, verified against the actual
// files on disk (never assumed). Progress 0 maps to frame 1, progress 1
// maps to this value.
export const TOTAL_CINEMATIC_FRAMES = 1200;
