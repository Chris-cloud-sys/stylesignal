/**
 * Result polling — spec §4.1 and §6.6.
 *
 * "Poll `GET /outfits/{id}` until status is `complete` or `failed`", at 1.5s
 * backing off to 4s. v2 replaces this with a websocket or push channel (§10);
 * the screen contract does not change when it does.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import {
  POLL_BACKOFF,
  POLL_INITIAL_MS,
  POLL_MAX_MS,
  POLL_TIMEOUT_MS,
} from '../config';
import { ApiError, fetchOutfit } from './client';
import type { OutfitDetail } from './types';

export type PollState =
  | { phase: 'loading'; outfit?: OutfitDetail }
  | { phase: 'settled'; outfit: OutfitDetail }
  | { phase: 'error'; message: string; outfit?: OutfitDetail };

export function useOutfitPolling(outfitId: string | null): {
  state: PollState;
  retry: () => void;
} {
  const [state, setState] = useState<PollState>({ phase: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const cancelled = useRef(false);

  const retry = useCallback(() => {
    setState({ phase: 'loading' });
    setAttempt((value) => value + 1);
  }, []);

  useEffect(() => {
    if (!outfitId) return;

    cancelled.current = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let delay = POLL_INITIAL_MS;
    const deadline = Date.now() + POLL_TIMEOUT_MS;

    const tick = async (): Promise<void> => {
      if (cancelled.current) return;
      try {
        const outfit = await fetchOutfit(outfitId);
        if (cancelled.current) return;

        if (outfit.status === 'complete' || outfit.status === 'failed') {
          setState({ phase: 'settled', outfit });
          return;
        }

        setState({ phase: 'loading', outfit });

        if (Date.now() > deadline) {
          setState({
            phase: 'error',
            message:
              'This is taking longer than expected. Your scan is still ' +
              'running — check your history in a moment.',
            outfit,
          });
          return;
        }

        delay = Math.min(delay * POLL_BACKOFF, POLL_MAX_MS);
        timer = setTimeout(tick, delay);
      } catch (error) {
        if (cancelled.current) return;
        setState({
          phase: 'error',
          message:
            error instanceof ApiError
              ? error.message
              : 'Could not reach StyleSignal. Check your connection.',
        });
      }
    };

    void tick();

    return () => {
      cancelled.current = true;
      if (timer) clearTimeout(timer);
    };
  }, [outfitId, attempt]);

  return { state, retry };
}
