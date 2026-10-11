// Fade-in for cards, CSS only: Tailwind's starting: variant (@starting-style) with a staggered delay. No motion
// when the viewer prefers reduced motion (the transition is removed, so cards simply appear).
import type { CSSProperties } from "react";

export const FADE_IN = "transition-opacity duration-200 ease-out starting:opacity-0 motion-reduce:transition-none";

const STAGGER_MS = 50;
const MAX_STEPS = 8; // long lists stop staggering after the first few cards

/** The i-th card's delay: 0, 50, 100 … ms, capped so a long list never waits long. */
export const stagger = (i: number): CSSProperties => ({ transitionDelay: `${Math.min(i, MAX_STEPS) * STAGGER_MS}ms` });
