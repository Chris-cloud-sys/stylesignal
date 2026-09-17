/**
 * The rail's Share button, wired to a real branded image — SPEC+
 * (docs/spec-deviations.md). Community's and Browse's own Share icon used
 * to be a bare `Share.share({message})` — text only, no photo, which read
 * as "Mike shared a read for the evening on StyleSignal" with nothing to
 * look at. `ResultScreen` already solved this correctly for the outfit's
 * own owner (captures the branded `ShareCard` to a PNG); this reuses that
 * exact mechanism for someone looking at a feed/browse card instead,
 * fetching the full feedback on demand — a feed card only ever carries a
 * `verdict_phrase`, not the full palette/meters `ShareCard` needs, and
 * fetching that for every card up front just in case it's shared would be
 * wasted work for the overwhelming majority never tapped.
 */
import { Ionicons } from '@expo/vector-icons';
import React, { useRef, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { fetchOutfit } from '../api/client';
import type { Feedback } from '../api/types';
import { shareFeedbackImage } from '../share';
import { colors } from '../theme';
import { ShareCard } from './ShareCard';

interface Props {
  outfitId: string;
  occasion?: string | null;
  thumbUri?: string | null;
  style?: StyleProp<ViewStyle>;
  iconColor?: string;
}

export function ShareOutfitAction({
  outfitId,
  occasion,
  thumbUri,
  style,
  iconColor = colors.onPhoto,
}: Props): React.ReactElement {
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const cardRef = useRef<View>(null);

  const share = async (): Promise<void> => {
    if (busy) return;
    setBusy(true);
    try {
      const detail = await fetchOutfit(outfitId);
      if (!detail.feedback) {
        // No feedback to build a card from (shouldn't happen for anything
        // reaching a feed/browse card, which are always "complete") —
        // fall back to a plain text share rather than nothing.
        setBusy(false);
        return;
      }
      // Mounting the off-screen ShareCard is what triggers the capture,
      // in the effect below, once it's actually had a render pass.
      setFeedback(detail.feedback);
    } catch {
      setBusy(false);
    }
  };

  return (
    <>
      <Pressable
        onPress={() => void share()}
        style={style}
        accessibilityRole="button"
        accessibilityLabel="Share this read"
      >
        {busy ? (
          <ActivityIndicator size="small" color={iconColor} />
        ) : (
          <Ionicons name="arrow-redo-outline" size={24} color={iconColor} />
        )}
      </Pressable>

      {feedback ? (
        <View style={styles.offscreen} pointerEvents="none">
          <ShareCard
            ref={cardRef}
            photoUri={thumbUri ?? undefined}
            occasion={occasion}
            feedback={feedback}
            format="story"
            onLayout={() => {
              // Capture only after the card has actually laid out — a ref
              // populated on mount but not yet rendered/measured captures
              // blank. See BrowseFeed's onScrollToIndexFailed for the same
              // "wait for a real layout pass" shape elsewhere in this app.
              void shareFeedbackImage(cardRef, feedback).finally(() => {
                setBusy(false);
                setFeedback(null);
              });
            }}
          />
        </View>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  offscreen: { position: 'absolute', top: -9999, left: -9999 },
});
