import Constants from 'expo-constants';
import { Platform } from 'react-native';

/**
 * Where the gateway lives.
 *
 * `localhost` inside an emulator is the emulator, not your machine:
 *   - Android emulator  -> 10.0.2.2
 *   - iOS simulator     -> 127.0.0.1 works
 *   - Physical device   -> your machine's LAN IP, set below or in app.json
 */
function defaultBaseUrl(): string {
  const fromConfig = (Constants.expoConfig?.extra as Record<string, unknown> | undefined)
    ?.apiBaseUrl;
  if (typeof fromConfig === 'string' && fromConfig.length > 0) {
    if (Platform.OS === 'android' && fromConfig.includes('127.0.0.1')) {
      return fromConfig.replace('127.0.0.1', '10.0.2.2');
    }
    return fromConfig;
  }
  return Platform.OS === 'android' ? 'http://10.0.2.2:8000' : 'http://127.0.0.1:8000';
}

export const API_BASE_URL = defaultBaseUrl();

/** §4.1 — downscale before upload to cut bandwidth. */
export const MAX_UPLOAD_LONGEST_EDGE = 1600;
export const UPLOAD_JPEG_QUALITY = 0.85;

/** §6.6 — poll at 1.5s, backing off to 4s. */
export const POLL_INITIAL_MS = 1500;
export const POLL_MAX_MS = 4000;
export const POLL_BACKOFF = 1.25;
export const POLL_TIMEOUT_MS = 90_000;

/** §5.3 occasion enum, in the order the chips are shown. */
export const OCCASIONS = [
  'casual',
  'work',
  'formal',
  'evening',
  'athletic',
  'other',
] as const;

export type Occasion = (typeof OCCASIONS)[number];

export const CONTEXT_NOTE_MAX_LENGTH = 280;

/**
 * Native IAP (SPEC+, docs/spec-deviations.md #18) — same product id on both
 * stores, matching the backend's `iap_product_id_ios`/`iap_product_id_android`
 * defaults in app/config.py. Must be created in App Store Connect and Play
 * Console with exactly this id before a real purchase can complete.
 */
export const PRO_SUBSCRIPTION_SKU = 'stylesignal_pro_monthly';
/** Shown only until the store returns a real, localized price. */
export const PRO_MONTHLY_PRICE_FALLBACK = '$4.99/month';
