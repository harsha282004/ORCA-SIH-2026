// Central place for frontend runtime configuration. Never hard-code the
// backend URL elsewhere — import API_BASE_URL from here instead.
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
