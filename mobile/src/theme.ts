/**
 * Design tokens — spec §2.6.
 *
 * The outfit photo is the hero, so the UI recedes. Ink + Bone carry ~90% of
 * every screen; Signal Amber is a signature, not a fill.
 *
 * Two rules here are product rules, not taste:
 *   1. Colour never delivers the verdict. Feedback is language (§7). There is
 *      deliberately no `success` / `warning` / `error` colour for feedback
 *      content — only for system state like a failed upload.
 *   2. Amber, not red. Red reads as judgement, which contradicts the
 *      descriptive, non-evaluative voice.
 *
 * White-label (§2.6): a tenant's `primary_color` replaces `accent` and nothing
 * else. Ink/Bone/Slate stay constant — that neutrality is what makes the base
 * themeable at all.
 */

export const palette = {
  ink: '#1A1A1A',
  bone: '#F4F0E9',
  accent: '#E0A32E', // Signal Amber — the lead accent
  indigo: '#2C4A7C', // the §2.6 fork; pick one accent, never run both
  slate: '#8A8578',
} as const;

export const colors = {
  background: palette.bone,
  surface: '#FBF9F5',
  text: palette.ink,
  textMuted: palette.slate,
  border: '#E2DCD0',
  accent: palette.accent,
  onAccent: palette.ink,
  /** System state only — never used to grade an outfit. */
  systemError: '#8C3A2B',
} as const;

export const space = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
} as const;

export const radius = {
  sm: 6,
  md: 12,
  lg: 20,
  pill: 999,
} as const;

/**
 * Two weights only (§2.6). `medium` is as heavy as the type ever gets —
 * there is no bold.
 */
export const weight = {
  regular: '400',
  medium: '500',
} as const;

export const type = {
  display: { fontSize: 30, lineHeight: 38, fontWeight: weight.regular },
  title: { fontSize: 22, lineHeight: 29, fontWeight: weight.medium },
  sectionLabel: {
    fontSize: 12,
    lineHeight: 16,
    fontWeight: weight.medium,
    letterSpacing: 0.8,
  },
  body: { fontSize: 16, lineHeight: 25, fontWeight: weight.regular },
  bodyMedium: { fontSize: 16, lineHeight: 25, fontWeight: weight.medium },
  meta: { fontSize: 13, lineHeight: 19, fontWeight: weight.regular },
} as const;

/**
 * Sentence case everywhere (§2.6). Use this instead of `textTransform:
 * 'uppercase'` when you are tempted — the one exception is the small section
 * label, where letter-spacing does the work instead.
 */
export const sentenceCase = (value: string): string =>
  value.length === 0 ? value : value[0]!.toUpperCase() + value.slice(1);
