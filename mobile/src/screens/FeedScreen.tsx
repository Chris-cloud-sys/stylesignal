/**
 * Community feed — spec §6.5, §4.8.
 *
 * Rate outfits other members have shared for community feedback to earn
 * scans (§1's earn-by-rating hook). Flag-gated server-side
 * (STYLESIGNAL_COMMUNITY_ENABLED) — see docs/spec-deviations.md #17. Rating
 * even one dimension on an outfit drops it from the feed for good (the
 * server excludes anything the caller has rated at all, not per-dimension —
 * see app/routers/feed.py), so "Submit rating" sends whichever dimensions
 * were touched and the card is gone either way.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { absoluteMediaUrl, fetchFeed, likeOutfit, rateOutfit, unlikeOutfit } from '../api/client';
import type { FeedItem, RatingDimension } from '../api/types';
import { Button } from '../components/primitives';
import { colors, radius, sentenceCase, space, type, weight } from '../theme';

interface Props {
  onBack: () => void;
  /** Lets App.tsx refresh the scans-left pill after an earn. */
  onRated: () => void;
}

/** Plain-language phrasing per occasion, for the occasion_fit question below
 * — "Does this look right for work?" reads clearer to a casual rater than
 * "right register for what it's tagged for", which assumes vocabulary the
 * app never explains anywhere else. */
const OCCASION_PHRASES: Record<string, string> = {
  casual: 'a casual day',
  work: 'work',
  formal: 'a formal event',
  evening: 'an evening out',
  athletic: 'workout or athletic wear',
};

const DIMENSIONS: Array<{
  key: RatingDimension;
  label: string;
  hint: (occasion: string | null | undefined) => string;
}> = [
  {
    key: 'coherence',
    label: 'Coherence',
    hint: () => 'Do the pieces look like they belong together?',
  },
  {
    key: 'occasion_fit',
    label: 'Occasion fit',
    hint: (occasion) =>
      `Does this look right for ${
        (occasion && OCCASION_PHRASES[occasion]) || "the occasion it's tagged for"
      }?`,
  },
  {
    key: 'color',
    label: 'Colour',
    hint: () => 'Do the colors work well together?',
  },
];

export function FeedScreen({ onBack, onRated }: Props): React.ReactElement {
  const [items, setItems] = useState<FeedItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async (nextCursor?: string | null): Promise<void> => {
    try {
      const page = await fetchFeed(nextCursor);
      setItems((existing) => (nextCursor ? [...existing, ...page.items] : page.items));
      setCursor(page.cursor ?? null);
      setError(null);
    } catch {
      setError('Could not load the community feed.');
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSubmitted = (outfitId: string, scansEarned: number): void => {
    setItems((existing) => existing.filter((item) => item.outfit_id !== outfitId));
    if (scansEarned > 0) {
      setNotice(`Earned ${scansEarned} scan${scansEarned === 1 ? '' : 's'} — thanks for rating.`);
      onRated();
    }
  };

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator color={colors.textMuted} />
      </View>
    );
  }

  return (
    <View style={styles.flex}>
      <View style={styles.header}>
        <Text style={styles.title}>Community</Text>
        <Pressable onPress={onBack} accessibilityRole="button">
          <Text style={styles.headerLink}>Done</Text>
        </Pressable>
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}
      {notice ? <Text style={styles.notice}>{notice}</Text> : null}

      <FlatList
        data={items}
        keyExtractor={(item) => item.outfit_id}
        contentContainerStyle={styles.list}
        ListEmptyComponent={
          <Text style={styles.empty}>
            Nothing to rate right now — check back once more members have
            shared a read.
          </Text>
        }
        onEndReachedThreshold={0.4}
        onEndReached={() => {
          if (cursor && !loadingMore) {
            setLoadingMore(true);
            void load(cursor);
          }
        }}
        ListFooterComponent={
          loadingMore ? <ActivityIndicator color={colors.textMuted} /> : null
        }
        renderItem={({ item }) => (
          <FeedCard
            item={item}
            onSubmitted={(earned) => handleSubmitted(item.outfit_id, earned)}
          />
        )}
      />
    </View>
  );
}

function FeedCard({
  item,
  onSubmitted,
}: {
  item: FeedItem;
  onSubmitted: (scansEarned: number) => void;
}): React.ReactElement {
  const [values, setValues] = useState<Partial<Record<RatingDimension, number>>>({});
  const [submitting, setSubmitting] = useState(false);
  const [liked, setLiked] = useState(item.liked_by_me);
  const [likeCount, setLikeCount] = useState(item.like_count);
  const [likeBusy, setLikeBusy] = useState(false);
  const thumb = absoluteMediaUrl(item.thumb_url);
  const hasAnyValue = Object.keys(values).length > 0;

  // SPEC+ — likes/favorites, no dislike counterpart. Separate from the 1-5
  // rating dimensions above: this is a lightweight favoriting action, not
  // training signal, so it doesn't touch the earn-by-rating loop and
  // doesn't drop the card from the feed the way submitting a rating does.
  const toggleLike = async (): Promise<void> => {
    if (likeBusy) return;
    const wasLiked = liked;
    setLikeBusy(true);
    setLiked(!wasLiked);
    setLikeCount((count) => count + (wasLiked ? -1 : 1));
    try {
      const response = wasLiked
        ? await unlikeOutfit(item.outfit_id)
        : await likeOutfit(item.outfit_id);
      setLiked(response.liked);
      setLikeCount(response.like_count);
    } catch {
      setLiked(wasLiked);
      setLikeCount((count) => count + (wasLiked ? 1 : -1));
    } finally {
      setLikeBusy(false);
    }
  };

  const submit = async (): Promise<void> => {
    if (!hasAnyValue || submitting) return;
    setSubmitting(true);
    let earned = 0;
    try {
      for (const [dimension, value] of Object.entries(values) as Array<
        [RatingDimension, number]
      >) {
        const response = await rateOutfit(item.outfit_id, dimension, value);
        earned += response.scans_earned;
      }
      onSubmitted(earned);
    } catch {
      // Leave the card as-is with its values intact — the user can retry.
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View style={styles.card}>
      {thumb ? (
        <Image source={{ uri: thumb }} style={styles.cardImage} resizeMode="cover" />
      ) : (
        <View style={[styles.cardImage, styles.cardImagePlaceholder]} />
      )}

      <View style={styles.cardHead}>
        {item.occasion ? (
          <Text style={styles.cardOccasion}>Occasion: {sentenceCase(item.occasion)}</Text>
        ) : (
          <View />
        )}
        <Pressable
          onPress={() => void toggleLike()}
          style={styles.likeButton}
          accessibilityRole="button"
          accessibilityLabel={liked ? 'Unlike this outfit' : 'Like this outfit'}
        >
          <Text style={[styles.likeGlyph, liked && styles.likeGlyphActive]}>
            {liked ? '♥' : '♡'}
          </Text>
          <Text style={styles.likeCount}>{likeCount}</Text>
        </Pressable>
      </View>

      {DIMENSIONS.map((dimension) => (
        <RatingRow
          key={dimension.key}
          label={dimension.label}
          hint={dimension.hint(item.occasion)}
          value={values[dimension.key]}
          onChange={(value) =>
            setValues((existing) => ({ ...existing, [dimension.key]: value }))
          }
        />
      ))}

      <Button
        label="Submit rating"
        onPress={() => void submit()}
        disabled={!hasAnyValue}
        busy={submitting}
        style={styles.cardSubmit}
      />
    </View>
  );
}

function RatingRow({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value?: number;
  onChange: (value: number) => void;
}): React.ReactElement {
  return (
    <View style={styles.ratingRow}>
      <Text style={styles.ratingLabel}>{label}</Text>
      <Text style={styles.ratingHint}>{hint}</Text>
      <View style={styles.ratingScale}>
        {[1, 2, 3, 4, 5].map((option) => {
          const selected = value === option;
          return (
            <Pressable
              key={option}
              onPress={() => onChange(option)}
              style={[styles.ratingDot, selected && styles.ratingDotSelected]}
              accessibilityRole="button"
              accessibilityLabel={`${label}: ${option} of 5`}
            >
              <Text
                style={[styles.ratingDotLabel, selected && styles.ratingDotLabelSelected]}
              >
                {option}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.background },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    paddingHorizontal: space.lg,
    paddingTop: space.lg,
    paddingBottom: space.md,
  },
  title: { ...type.title, color: colors.text },
  headerLink: { ...type.meta, color: colors.textMuted },
  list: { paddingHorizontal: space.lg, paddingBottom: space.xxl },
  empty: { ...type.body, color: colors.textMuted, marginTop: space.xl },
  error: {
    ...type.meta,
    color: colors.systemError,
    paddingHorizontal: space.lg,
    marginBottom: space.sm,
  },
  notice: {
    ...type.meta,
    color: colors.text,
    backgroundColor: '#FAF2E1',
    paddingHorizontal: space.lg,
    paddingVertical: space.sm,
    marginHorizontal: space.lg,
    borderRadius: radius.md,
    marginBottom: space.md,
  },

  card: {
    marginBottom: space.xl,
    paddingBottom: space.lg,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  cardImage: {
    width: '100%',
    aspectRatio: 3 / 4,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    marginBottom: space.sm,
  },
  cardImagePlaceholder: { borderWidth: 1, borderColor: colors.border },
  cardHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: space.md,
  },
  cardOccasion: { ...type.meta, color: colors.textMuted },
  // §2.6: amber is the accent, never red — a liked heart stays on-brand
  // rather than reaching for the conventional red fill.
  likeButton: { flexDirection: 'row', alignItems: 'center', gap: space.xs, padding: space.xs },
  likeGlyph: { fontSize: 18, color: colors.textMuted },
  likeGlyphActive: { color: colors.accent },
  likeCount: { ...type.meta, color: colors.textMuted },
  cardSubmit: { marginTop: space.sm },

  ratingRow: { marginBottom: space.md },
  ratingLabel: { ...type.bodyMedium, color: colors.text },
  ratingHint: { ...type.meta, color: colors.textMuted, marginTop: 2, marginBottom: space.sm },
  ratingScale: { flexDirection: 'row', gap: space.sm },
  ratingDot: {
    width: 36,
    height: 36,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  ratingDotSelected: { borderColor: colors.text, backgroundColor: colors.text },
  ratingDotLabel: { ...type.meta, color: colors.textMuted, fontWeight: weight.medium },
  ratingDotLabelSelected: { color: colors.background },
});
