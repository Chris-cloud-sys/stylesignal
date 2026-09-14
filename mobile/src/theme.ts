/**
 * Design tokens — spec §2.6 (superseded in part, see below).
 *
 * The outfit photo is the hero, so the UI recedes. Ink/Bone/Amber has been
 * replaced with a light/dark-aware Electric Sky / Neon Cyan system —
 * SPEC+, a deliberate rebrand, see docs/spec-deviations.md.
 *
 * What changed from the original §2.6 and what didn't:
 *   1. STILL TRUE, on purpose: "colour never delivers the verdict" still
 *      holds for outfit content. `colors.signal` (Coral/Neon Coral) is
 *      defined — it was part of the rebrand brief — but deliberately NOT
 *      applied anywhere on a read, a quick-read, or any other outfit-
 *      judgment surface. It's reserved for clearly non-judgment UI (a
 *      "new" badge, a system notice) if a specific feature ever wants it.
 *      Defining the token cost nothing; using it on content would have
 *      reopened the exact rule this file exists to enforce.
 *   2. STILL TRUE: `colors.systemError` stays reserved for genuine system
 *      failures (a failed upload), not for grading an outfit — it shares
 *      a hue family with `signal` but is a separate token for a separate,
 *      narrower purpose.
 *   3. STILL TRUE: white-label — a tenant's `primary_color` replaces
 *      `accent` and nothing else.
 *
 * Light/dark resolution happens ONCE, at module load, not live — every
 * screen already reads plain `colors.X` values baked into a module-scope
 * `StyleSheet.create(...)`, not a hook, so there is nothing to re-render
 * if the theme changes while the app is already open. Wiring true live-
 * switching would mean moving every screen's stylesheet into a hook — a
 * much larger refactor, deliberately out of scope here.
 *
 * A user's explicit Light/Dark/System choice (Profile → Appearance) is
 * still applied without a manual restart, though: `setThemePreference`
 * writes the choice with `SecureStore.setItem` (the synchronous variant,
 * not `setItemAsync` — deliberately, so the value is readable
 * synchronously below, before any other module's `StyleSheet.create`
 * call runs) and then calls `Updates.reloadAsync()`, which restarts the
 * JS engine against the same installed bundle. That re-runs every
 * module's top-level code from scratch, including this file, which is
 * what actually makes the new preference take effect everywhere at once
 * — not a live re-render, a full (near-instant) reload.
 */
import { Appearance } from 'react-native';
import * as SecureStore from 'expo-secure-store';

export type ThemePreference = 'light' | 'dark' | 'system';

const THEME_PREFERENCE_KEY = 'stylesignal.theme_preference';

/** Synchronous on purpose — see the module header. */
function readStoredPreference(): ThemePreference {
  try {
    const value = SecureStore.getItem(THEME_PREFERENCE_KEY);
    if (value === 'light' || value === 'dark') return value;
  } catch {
    // SecureStore unavailable (e.g. a platform without a keychain) —
    // fall back to following the OS.
  }
  return 'system';
}

export function getThemePreference(): ThemePreference {
  return readStoredPreference();
}

/** Persists the choice and reloads immediately so it actually takes
 * effect — see the module header for why a reload, not a live update. */
export async function setThemePreference(preference: ThemePreference): Promise<void> {
  try {
    if (preference === 'system') {
      await SecureStore.deleteItemAsync(THEME_PREFERENCE_KEY);
    } else {
      SecureStore.setItem(THEME_PREFERENCE_KEY, preference);
    }
  } catch {
    // Best-effort — worst case the choice doesn't persist and the app
    // falls back to following the OS on next launch.
  }
  const Updates = await import('expo-updates');
  await Updates.reloadAsync();
}

const lightPalette = {
  background: '#FAFAFA', // Crisp Chalk White
  surface: '#F1F3F5', // Soft Editorial Gray
  text: '#1A1A1A', // Onyx Ink
  textMuted: '#5B6570',
  border: '#E2E5E9',
  accent: '#00A3E0', // Electric Sky
  onAccent: '#FFFFFF',
  systemError: '#FF5A5F', // Coral Alert
  signal: '#FF5A5F', // same hue as systemError, different purpose — see header
  badgeBackground: '#E3F4FC', // soft accent-tinted icon-badge fill
} as const;

const darkPalette = {
  background: '#0D0F14', // Midnight Ink — never pure black, or the UI flattens
  surface: '#181E29', // Deep Slate
  text: '#E4E4E7', // Soft Frost
  textMuted: '#9CA3AF',
  border: '#262D3A',
  accent: '#38BDF8', // Neon Cyan — already toned down from a fully saturated
  // sky blue, so it doesn't vibrate against Midnight Ink.
  onAccent: '#0D0F14',
  systemError: '#FF6B6B', // Neon Coral
  signal: '#FF6B6B',
  badgeBackground: '#152736',
} as const;

// An explicit stored choice wins outright; "system" (the default, nothing
// stored yet) falls back to the OS setting exactly as before.
const preference = readStoredPreference();
const resolvedScheme = preference === 'system' ? Appearance.getColorScheme() : preference;
const active = resolvedScheme === 'dark' ? darkPalette : lightPalette;

/** Resolved once at launch, same as `colors` — see the module header for
 * why this isn't live. Lets App.tsx pick a status-bar icon style that's
 * actually visible against the resolved background. */
export const isDarkMode = resolvedScheme === 'dark';

export const colors = {
  background: active.background,
  surface: active.surface,
  text: active.text,
  textMuted: active.textMuted,
  border: active.border,
  accent: active.accent,
  onAccent: active.onAccent,
  /** System state only — never used to grade an outfit. */
  systemError: active.systemError,
  /** SPEC+ — reserved, not yet used anywhere. Not for outfit content —
   * see the module header. Only for a future non-judgment UI surface (a
   * "new" badge, a system notice), if one is ever deliberately designed
   * to need it. */
  signal: active.signal,
  /** Soft accent-tinted fill for icon badges (quick-read icons, capture
   * mode icon, the "one idea" box) — was a hardcoded amber tint in each
   * of those files; centralised here so it follows the accent and the
   * light/dark mode instead of drifting out of sync with it. */
  badgeBackground: active.badgeBackground,
  /** Fixed, NOT theme-dependent — text/icons rendered over a photo's own
   * dark scrim (the hero verdict overlay, the rail icons on a feed/read
   * photo). The scrim itself is a hardcoded dark overlay regardless of
   * app theme, because it's providing contrast against an arbitrary
   * photo, not against the app's chrome — so the text on it needs a
   * fixed light colour too. Before this token existed, those spots used
   * `colors.background`/`colors.surface` as a stand-in for "light
   * colour," which broke the moment those tokens became theme-dependent:
   * in dark mode they resolved to near-black, rendering as dark text on
   * a dark photo scrim — illegible. See docs/spec-deviations.md.
   */
  onPhoto: '#F2F2F2',
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
