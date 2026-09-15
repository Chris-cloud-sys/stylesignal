/** Favorites — outfits the caller has explicitly bookmarked, separate from
 * liking (SPEC+, docs/spec-deviations.md). A photo grid (see
 * components/PhotoGrid.tsx) — was a row list with an always-visible
 * "Remove" per row; long-press-to-select replaces that, same as History. */
import { Ionicons } from '@expo/vector-icons';
import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { absoluteMediaUrl, fetchFavorites, unfavoriteOutfit } from '../api/client';
import type { OutfitListItem } from '../api/types';
import { GridStatusBadge, PhotoGrid } from '../components/PhotoGrid';
import { colors, space, type } from '../theme';

interface Props {
  onOpen: (outfitId: string) => void;
  /** SPEC+ — genuinely browsable Favorites (docs/spec-deviations.md #42). */
  onBrowse: (items: OutfitListItem[], initialIndex: number) => void;
}

export function FavoritesScreen({ onOpen, onBrowse }: Props): React.ReactElement {
  const [items, setItems] = useState<OutfitListItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const selecting = selected.size > 0;

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

  const toggleSelect = (outfitId: string): void => {
    setSelected((existing) => {
      const next = new Set(existing);
      if (next.has(outfitId)) {
        next.delete(outfitId);
      } else {
        next.add(outfitId);
      }
      return next;
    });
  };

  // SPEC+ — genuinely browsable Favorites (docs/spec-deviations.md #42).
  const openItem = (item: OutfitListItem): void => {
    if (item.status !== 'complete') {
      onOpen(item.outfit_id);
      return;
    }
    Alert.alert('Open this favorite', undefined, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Read', onPress: () => onOpen(item.outfit_id) },
      {
        text: 'Browse',
        onPress: () => onBrowse(items, items.findIndex((i) => i.outfit_id === item.outfit_id)),
      },
    ]);
  };

  const removeSelected = (): void => {
    const ids = Array.from(selected);
    setItems((existing) => existing.filter((item) => !selected.has(item.outfit_id)));
    setSelected(new Set());
    Promise.all(ids.map((id) => unfavoriteOutfit(id))).catch(() => void load());
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
        {selecting ? (
          <>
            <Pressable
              onPress={() => setSelected(new Set())}
              accessibilityRole="button"
              accessibilityLabel="Cancel selection"
            >
              <Text style={styles.headerLink}>Cancel</Text>
            </Pressable>
            <Text style={styles.title}>{selected.size} selected</Text>
            <Pressable
              onPress={removeSelected}
              accessibilityRole="button"
              accessibilityLabel="Remove selected favorites"
              hitSlop={8}
            >
              <Ionicons name="bookmark" size={22} color={colors.accent} />
            </Pressable>
          </>
        ) : (
          <Text style={styles.title}>Favorites</Text>
        )}
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <PhotoGrid
        data={items}
        keyExtractor={(item) => item.outfit_id}
        getThumbUrl={(item) => absoluteMediaUrl(item.thumb_url)}
        onPress={(item) => (selecting ? toggleSelect(item.outfit_id) : openItem(item))}
        onLongPress={(item) => toggleSelect(item.outfit_id)}
        isSelected={(item) => selected.has(item.outfit_id)}
        selecting={selecting}
        renderBadge={(item) => <GridStatusBadge status={item.status} />}
        accessibilityLabel={(item) =>
          item.occasion ? `${item.occasion} favorite` : 'Favorite with no occasion tagged'
        }
        emptyText="Nothing here yet. Tap the bookmark on a read in Community to save it here."
        cursor={cursor}
        loadingMore={loadingMore}
        onEndReached={() => {
          if (cursor && !loadingMore) {
            setLoadingMore(true);
            void load(cursor);
          }
        }}
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
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: space.lg,
    paddingTop: space.lg,
    paddingBottom: space.md,
  },
  title: { ...type.title, color: colors.text },
  headerLink: { ...type.body, color: colors.accent },
  error: {
    ...type.meta,
    color: colors.systemError,
    paddingHorizontal: space.lg,
    marginBottom: space.sm,
  },
});
