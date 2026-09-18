/**
 * Shared "share a read" helpers — SPEC+ (docs/spec-deviations.md). Pulled
 * out of ResultScreen.tsx so the Community feed and Browse feed's own
 * Share actions can reuse the exact same branded-image capture instead of
 * each doing a bare `Share.share({message})` text-only share (the "no
 * image, just text" bug).
 */
import { File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';
import type { RefObject } from 'react';
import { Share, type View } from 'react-native';
import { captureRef } from 'react-native-view-shot';

import type { Feedback } from './api/types';
import { sentenceCase } from './theme';

export function buildShareText(feedback: Feedback): string {
  const lines = [feedback.verdict_phrase];
  if (feedback.verdict_subtitle) lines.push(feedback.verdict_subtitle);
  if (feedback.quick_reads.length > 0) {
    lines.push('');
    for (const item of feedback.quick_reads) {
      lines.push(`${sentenceCase(item.dimension)}: ${item.text}`);
    }
  }
  lines.push('');
  // "Try it now" phase 1 — same brand-only line as ShareCard's watermark,
  // no domain/store link until phase 2 has one to point at.
  lines.push('Get your own read — StyleSignal');
  return lines.join('\n');
}

export function shareFeedbackText(feedback: Feedback): void {
  Share.share({ message: buildShareText(feedback) }).catch(() => {
    // User cancelled or the share sheet failed to open — nothing to recover.
  });
}

/** Captures the off-screen ShareCard (components/ShareCard.tsx) to a PNG
 * and hands it to the native share sheet. Falls back to a text-only share
 * if the image capture or the share sheet itself is unavailable, so this
 * degrades gracefully rather than dead-ending. */
export async function shareFeedbackImage(
  cardRef: RefObject<View | null>,
  feedback: Feedback,
): Promise<void> {
  // SPEC+ (docs/spec-deviations.md) — two prior fixes here (onLayout-based
  // capture, then Image.prefetch) each addressed a real cause but the photo
  // is STILL reported missing from the shared image. Every failure path in
  // this function previously swallowed its error and fell back silently to
  // a text-only share, which is exactly why this has been guessed at twice
  // instead of diagnosed: there was never any visibility into which step
  // actually failed, or whether "failed" even happened (a capture that
  // *succeeds* but paints a blank photo looks identical from the outside).
  // TEMPORARY instrumentation — grep logcat for "[ShareDebug]" during a
  // live repro, then remove once the real cause is confirmed.
  console.log('[ShareDebug] shareFeedbackImage start', { hasCardRef: !!cardRef.current });
  try {
    const canShareFile = await Sharing.isAvailableAsync();
    console.log('[ShareDebug] Sharing.isAvailableAsync', canShareFile);
    if (!canShareFile || !cardRef.current) {
      console.log('[ShareDebug] falling back to text: no share sheet or no card ref');
      shareFeedbackText(feedback);
      return;
    }
    // react-native-view-shot's own tmp directory isn't one expo-sharing's
    // FileProvider config covers on Android — sharing straight from there
    // throws a native FileProvider exception that crashes the app instead
    // of rejecting the promise, so this try/catch never even sees it.
    // Copying into expo-file-system's cache dir first keeps the file
    // somewhere Sharing.shareAsync is actually configured to hand off.
    const capturedUri = await captureRef(cardRef, { format: 'png', quality: 1 });
    const capturedFile = new File(capturedUri);
    console.log('[ShareDebug] captureRef done', {
      capturedUri,
      exists: capturedFile.exists,
      size: capturedFile.exists ? capturedFile.size : null,
    });
    const shareableFile = new File(Paths.cache, `stylesignal-share-${Date.now()}.png`);
    capturedFile.copy(shareableFile);
    console.log('[ShareDebug] copied to cache', { uri: shareableFile.uri, size: shareableFile.size });
    await Sharing.shareAsync(shareableFile.uri, {
      mimeType: 'image/png',
      dialogTitle: 'Share this read',
    });
    console.log('[ShareDebug] Sharing.shareAsync resolved');
  } catch (err) {
    // Capture or the share sheet failed (or the user cancelled) — text still
    // gets the read across.
    console.log('[ShareDebug] caught error, falling back to text', err);
    shareFeedbackText(feedback);
  }
}
