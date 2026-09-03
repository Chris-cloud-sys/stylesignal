/** Wire types — spec §6. Kept 1:1 with the backend's Pydantic schemas. */

export type OutfitStatus = 'pending' | 'processing' | 'complete' | 'failed';

export type FailureReason =
  | 'undecodable'
  | 'no_person'
  | 'no_garments_detected'
  | 'internal_error';

export type GarmentCategory =
  | 'top'
  | 'bottom'
  | 'outerwear'
  | 'dress'
  | 'footwear'
  | 'accessory'
  | 'headwear';

export interface Colour {
  hex: string;
  weight: number;
}

export interface Garment {
  garment_id: string;
  category: GarmentCategory;
  colors: Colour[];
  pattern: string;
  formality: number;
}

export interface GarmentNote {
  garment_id?: string | null;
  note: string;
}

/** §7.7 — a glanceable meter. Computed deterministically on the backend
 * (never asked of the VLM), so `level` is always one of these three. */
export interface Meter {
  level: 'strong' | 'partial' | 'off';
  score: number;
}

export interface QuickRead {
  dimension: string;
  text: string;
}

/** The pre-§7.7 long-form fields, unchanged — now collapsed behind "See
 * full read" instead of shown by default. */
export interface FullRead {
  overall_read: string;
  color_note: string;
  formality_note: string;
  proportion_note?: string | null;
  garment_notes: GarmentNote[];
}

/**
 * §5.5 / §7.7 — the descriptive fields. All prose or a computed meter; never
 * a score of the wearer (§7.3). Zone 1+2 fields are top-level; the long-form
 * read lives under `full_read`.
 */
export interface Feedback {
  verdict_phrase: string;
  verdict_subtitle: string;
  occasion_match?: Meter | null;
  signal_clarity?: Meter | null;
  palette: Colour[];
  focal_point?: string | null;
  quick_reads: QuickRead[];
  full_read: FullRead;
}

export interface OutfitDetail {
  outfit_id: string;
  status: OutfitStatus;
  failure_reason?: FailureReason;
  occasion?: string | null;
  context_note?: string | null;
  is_public?: boolean;
  thumb_url?: string | null;
  created_at?: string;
  completed_at?: string | null;
  garments?: Garment[];
  feedback?: Feedback;
  /** SPEC+ — likes/favorites. Present only once shared (see docs/spec-
   * deviations.md); absent, not zero, means "never shared". */
  like_count?: number | null;
}

export interface OutfitListItem {
  outfit_id: string;
  status: OutfitStatus;
  thumb_url?: string | null;
  occasion?: string | null;
  created_at: string;
  like_count?: number | null;
}

export interface OutfitListResponse {
  items: OutfitListItem[];
  cursor?: string | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface Quota {
  plan: string;
  scans_used_this_month: number;
  monthly_allowance: number | null;
  earned_scans: number;
  scans_remaining: number | null;
  rating_credits: number;
  ratings_until_next_scan: number;
  /** SPEC+ — native IAP (docs/spec-deviations.md #18). Set only while
   * `plan === 'pro'`; a lapsed subscription reports as free instead. */
  pro_expires_at?: string | null;
}

export interface Me {
  user: {
    id: string;
    email: string;
    display_name: string;
    plan: string;
    is_stylist: boolean;
    created_at: string;
  };
  quota: Quota;
}

/** §6 error envelope. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

// --- Community rating loop (§6.5) — flag-gated, see docs/spec-deviations.md #17.
export type RatingDimension = 'coherence' | 'occasion_fit' | 'color';

export interface FeedItem {
  outfit_id: string;
  thumb_url?: string | null;
  occasion?: string | null;
  like_count: number;
  liked_by_me: boolean;
}

export interface LikeResponse {
  outfit_id: string;
  liked: boolean;
  like_count: number;
}

export interface FeedResponse {
  items: FeedItem[];
  cursor?: string | null;
}

export interface RatingResponse {
  outfit_id: string;
  dimension: RatingDimension;
  value: number;
  scans_earned: number;
  quota: Quota;
}

// --- Native in-app purchases (§SPEC+, see docs/spec-deviations.md #18) -----
export type IapPlatform = 'ios' | 'android';
