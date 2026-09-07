/**
 * Gateway client — spec §6.
 *
 * Holds the token pair in SecureStore, refreshes an expired access token once
 * per request, and surfaces the §6 error envelope as a typed `ApiError` so
 * screens can branch on `code` rather than parse messages.
 */
import * as SecureStore from 'expo-secure-store';

import { API_BASE_URL } from '../config';
import type {
  ApiErrorBody,
  FeedResponse,
  IapPlatform,
  LikeResponse,
  Me,
  OutfitDetail,
  OutfitListResponse,
  Quota,
  RatingDimension,
  RatingResponse,
  TokenPair,
} from './types';

const ACCESS_KEY = 'stylesignal.access_token';
const REFRESH_KEY = 'stylesignal.refresh_token';

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** §1 — the free allowance is spent. */
  get isQuotaExceeded(): boolean {
    return this.code === 'quota_exceeded';
  }

  get isAuthError(): boolean {
    return this.status === 401;
  }
}

let accessToken: string | null = null;
let refreshToken: string | null = null;

export async function loadStoredSession(): Promise<boolean> {
  accessToken = await SecureStore.getItemAsync(ACCESS_KEY);
  refreshToken = await SecureStore.getItemAsync(REFRESH_KEY);
  return accessToken !== null;
}

async function storeTokens(tokens: TokenPair): Promise<void> {
  accessToken = tokens.access_token;
  refreshToken = tokens.refresh_token;
  await SecureStore.setItemAsync(ACCESS_KEY, tokens.access_token);
  await SecureStore.setItemAsync(REFRESH_KEY, tokens.refresh_token);
}

export async function clearSession(): Promise<void> {
  accessToken = null;
  refreshToken = null;
  await SecureStore.deleteItemAsync(ACCESS_KEY);
  await SecureStore.deleteItemAsync(REFRESH_KEY);
}

export function hasSession(): boolean {
  return accessToken !== null;
}

async function parseError(response: Response): Promise<ApiError> {
  let code = 'http_error';
  let message = `Request failed (${response.status})`;
  let details: Record<string, unknown> = {};
  try {
    const body = (await response.json()) as ApiErrorBody;
    if (body?.error) {
      code = body.error.code ?? code;
      message = body.error.message ?? message;
      details = body.error.details ?? {};
    }
  } catch {
    // Non-JSON error body; keep the defaults.
  }
  return new ApiError(response.status, code, message, details);
}

interface RequestOptions {
  method?: string;
  body?: BodyInit | null;
  headers?: Record<string, string>;
  authenticated?: boolean;
  /** Internal: prevents an infinite refresh loop. */
  isRetry?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const {
    method = 'GET',
    body = null,
    headers = {},
    authenticated = true,
    isRetry = false,
  } = options;

  const finalHeaders: Record<string, string> = { ...headers };
  if (authenticated && accessToken) {
    finalHeaders.Authorization = `Bearer ${accessToken}`;
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: finalHeaders,
    body,
  });

  if (response.status === 401 && authenticated && !isRetry && refreshToken) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      return request<T>(path, { ...options, isRetry: true });
    }
    await clearSession();
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

async function tryRefresh(): Promise<boolean> {
  if (!refreshToken) return false;
  try {
    const response = await fetch(`${API_BASE_URL}/v1/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!response.ok) return false;
    await storeTokens((await response.json()) as TokenPair);
    return true;
  } catch {
    return false;
  }
}

function json(payload: unknown): RequestOptions {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    authenticated: false,
  };
}

// --- Auth ------------------------------------------------------------------
export async function register(
  email: string,
  password: string,
  displayName: string,
): Promise<void> {
  const tokens = await request<TokenPair>(
    '/v1/auth/register',
    json({ email, password, display_name: displayName }),
  );
  await storeTokens(tokens);
}

export async function login(email: string, password: string): Promise<void> {
  const tokens = await request<TokenPair>(
    '/v1/auth/login',
    json({ email, password }),
  );
  await storeTokens(tokens);
}

export function fetchMe(): Promise<Me> {
  return request<Me>('/v1/auth/me');
}

export function requestPasswordReset(email: string): Promise<void> {
  return request<{ status: string }>(
    '/v1/auth/password-reset/request',
    json({ email }),
  ).then(() => undefined);
}

export function confirmPasswordReset(
  email: string,
  code: string,
  newPassword: string,
): Promise<void> {
  return request<{ status: string }>(
    '/v1/auth/password-reset/confirm',
    json({ email, code, new_password: newPassword }),
  ).then(() => undefined);
}

// --- Outfits (§6.1-§6.4) ---------------------------------------------------
export async function uploadOutfit(params: {
  uri: string;
  occasion?: string | null;
  contextNote?: string | null;
  captureMode?: string;
  isPublic?: boolean;
}): Promise<{ outfit_id: string; status: string }> {
  const form = new FormData();
  // React Native's FormData takes this shape for a file part.
  form.append('image', {
    uri: params.uri,
    name: 'outfit.jpg',
    type: 'image/jpeg',
  } as unknown as Blob);

  if (params.occasion) form.append('occasion', params.occasion);
  if (params.contextNote) form.append('context_note', params.contextNote);
  if (params.captureMode) form.append('capture_mode', params.captureMode);
  form.append('is_public', params.isPublic ? 'true' : 'false');

  // Do not set Content-Type — the runtime adds the multipart boundary.
  return request<{ outfit_id: string; status: string }>('/v1/outfits', {
    method: 'POST',
    body: form as unknown as BodyInit,
  });
}

export function fetchOutfit(outfitId: string): Promise<OutfitDetail> {
  return request<OutfitDetail>(`/v1/outfits/${outfitId}`);
}

/** Result-screen "change occasion & re-read" — a real scan against the same
 * photo, not a free cache hit (the backend explains why in reread_outfit's
 * docstring). Returns the new outfit the same shape as uploadOutfit. */
export function rereadOutfit(
  outfitId: string,
  occasion: string | null,
): Promise<{ outfit_id: string; status: string }> {
  return request<{ outfit_id: string; status: string }>(
    `/v1/outfits/${outfitId}/reread`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ occasion }),
    },
  );
}

export function fetchHistory(cursor?: string | null): Promise<OutfitListResponse> {
  const query = cursor ? `?limit=20&cursor=${encodeURIComponent(cursor)}` : '?limit=20';
  return request<OutfitListResponse>(`/v1/outfits${query}`);
}

export function deleteOutfit(outfitId: string): Promise<void> {
  return request<void>(`/v1/outfits/${outfitId}`, { method: 'DELETE' });
}

/** Outfits the caller has liked, most-recently-liked first. */
export function fetchFavorites(cursor?: string | null): Promise<OutfitListResponse> {
  const query = cursor ? `?limit=20&cursor=${encodeURIComponent(cursor)}` : '?limit=20';
  return request<OutfitListResponse>(`/v1/outfits/favorites${query}`);
}

// --- Community rating loop (§6.5) -------------------------------------------
export function fetchFeed(cursor?: string | null): Promise<FeedResponse> {
  const query = cursor ? `?limit=20&cursor=${encodeURIComponent(cursor)}` : '?limit=20';
  return request<FeedResponse>(`/v1/feed${query}`);
}

export function rateOutfit(
  outfitId: string,
  dimension: RatingDimension,
  value: number,
): Promise<RatingResponse> {
  return request<RatingResponse>(`/v1/outfits/${outfitId}/ratings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dimension, value }),
  });
}

/** SPEC+ — likes/favorites, no dislike counterpart (docs/spec-deviations.md). */
export function likeOutfit(outfitId: string): Promise<LikeResponse> {
  return request<LikeResponse>(`/v1/outfits/${outfitId}/likes`, { method: 'POST' });
}

export function unlikeOutfit(outfitId: string): Promise<LikeResponse> {
  return request<LikeResponse>(`/v1/outfits/${outfitId}/likes`, { method: 'DELETE' });
}

// --- Billing (SPEC+ — native IAP, docs/spec-deviations.md #18) -------------
export function verifyPurchase(params: {
  platform: IapPlatform;
  productId: string;
  purchaseToken?: string | null;
  receiptData?: string | null;
}): Promise<Quota> {
  return request<Quota>('/v1/billing/verify-purchase', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      platform: params.platform,
      product_id: params.productId,
      purchase_token: params.purchaseToken,
      receipt_data: params.receiptData,
    }),
  });
}

/** Signed media URLs are returned as paths by the local storage backend. */
export function absoluteMediaUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  return url.startsWith('http') ? url : `${API_BASE_URL}${url}`;
}
