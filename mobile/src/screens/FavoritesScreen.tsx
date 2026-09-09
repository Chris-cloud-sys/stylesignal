/** Favorites — outfits the caller has explicitly bookmarked, separate from
 * liking (SPEC+, docs/spec-deviations.md). */
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

import { absoluteMediaUrl, fetchFavorites, unfavoriteOutfit } from '../api/client';
import type { OutfitListItem } from '../api/types';
import { Button } from '../components/primitives';
import { colors, radius, sentenceCase, space, type } from '../theme';

interface Props {
  onOpen: (outfitId: string) => void;
}

export function FavoritesScreen({ onOpen }: Props): React.ReactElement {
  const [items, setItems] = useState<OutfitListItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (nextCursor?: string | null): Promise<void> => {
    try {
      const page = await fetchFavorites(nextCursor);
      setItems((existing) =>
        nextCursor ? [...existing, ...page.items] : page.items,
      );
      setCursor(page.cursor ?? null);
      setError(null);
    } catch {
      setError('Could not load your favorites.');
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const remove = async (outfitId: string): Promise<void> => {
    setItems((existing) => existing.filter((item) => item.outfit_id !== outfitId));
    try {
      await unfavoriteOutfit(outfitId);
    } catch {
      void load();
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
        <Text style={styles.title}>Favorites</Text>
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <FlatList
        data={items}
        keyExtractor={(item) => item.outfit_id}
        contentContainerStyle={styles.list}
        ListEmptyComponent={
          <Text style={styles.empty}>
            Nothing here yet. Tap the bookmark on a read in Community to
            save it here.
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
          <Pressable
            style={styles.row}
            onPress={() => onOpen(item.outfit_id)}
            accessibilityRole="button"
          >
            {item.thumb_url ? (
              <Image
                source={{ uri: absoluteMediaUrl(item.thumb_url) }}
                style={styles.thumb}
                resizeMode="cover"
              />
            ) : (
              <View style={[styles.thumb, styles.thumbPlaceholder]} />
            )}

            <View style={styles.rowBody}>
              <Text style={styles.rowTitle}>
                {item.occasion ? sentenceCase(item.occasion) : 'No occasion tagged'}
              </Text>
              <Text style={styles.rowMeta}>
                {typeof item.like_count === 'number'
                  ? `${item.like_count} ${item.like_count === 1 ? 'like' : 'likes'}`
                  : 'Shared with the community'}
              </Text>
            </View>

            <Button
              variant="quiet"
              label="Remove"
              onPress={() => void remove(item.outfit_id)}
            />
          </Pressable>
        )}
      />
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
    paddingHorizontal: space.lg,
    paddingTop: space.lg,
    paddingBottom: space.md,
  },
  title: { ...type.title, color: colors.text },
  list: { paddingHorizontal: space.lg, paddingBottom: space.xxl },
  empty: { ...type.body, color: colors.textMuted, marginTop: space.xl },
  error: {
    ...type.meta,
    color: colors.systemError,
    paddingHorizontal: space.lg,
    marginBottom: space.sm,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: space.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  thumb: {
    width: 56,
    height: 72,
    borderRadius: radius.sm,
    backgroundColor: colors.surface,
  },
  thumbPlaceholder: { borderWidth: 1, borderColor: colors.border },
  rowBody: { flex: 1, paddingHorizontal: space.md },
  rowTitle: { ...type.bodyMedium, color: colors.text },
  rowMeta: { ...type.meta, color: colors.textMuted, marginTop: space.xs },
});
