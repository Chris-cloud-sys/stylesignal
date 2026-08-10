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

/** §5.5 — the descriptive fields. All prose; never a score (§7.3). */
export interface Feedback {
  overall_read: string;
  color_note: string;
  formality_note: string;
  proportion_note?: string | null;
  garment_notes: GarmentNote[];
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
}

export interface OutfitListItem {
  outfit_id: string;
  status: OutfitStatus;
  thumb_url?: string | null;
  occasion?: string | null;
  created_at: string;
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
