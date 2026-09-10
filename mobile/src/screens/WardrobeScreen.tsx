/**
 * Wardrobe catalog — SPEC+ (docs/spec-deviations.md).
 *
 * A conscious reversal of the original "no wardrobe to catalogue" decision,
 * scoped narrowly: items are bootstrapped from "item, not worn" scans only,
 * reusing a capture flow that already exists rather than asking for a
 * second, dedicated cataloguing ritual.
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

import { absoluteMediaUrl, fetchWardrobe, removeFromWardrobe } from '../api/client';
import type { WardrobeItem } from '../api/types';
import { Button } from '../components/primitives';
import { colors, radius, sentenceCase, space, type } from '../theme';

interface Props {
  onBack: () => void;
  onOpenOutfit: (outfitId: string) => void;
}

export function WardrobeScreen({ onBack, onOpenOutfit }: Props): React.ReactElement {
  const [items, setItems] = useState<WardrobeItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (nextCursor?: string | null): Promise<void> => {
    try {
      const page = await fetchWardrobe(nextCursor);
      setItems((existing) => (nextCursor ? [...existing, ...page.items] : page.items));
      setCursor(page.cursor ?? null);
      setError(null);
    } catch {
      setError('Could not load your wardrobe.');
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const remove = async (itemId: string): Promise<void> => {
    setItems((existing) => existing.filter((item) => item.item_id !== itemId));
    try {
      await removeFromWardrobe(itemId);
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
        <Pressable onPress={onBack} accessibilityRole="button">
          <Text style={styles.backLink}>Back</Text>
        </Pressable>
        <Text style={styles.title}>Wardrobe</Text>
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <FlatList
        data={items}
        keyExtractor={(item) => item.item_id}
        contentContainerStyle={styles.list}
        ListEmptyComponent={
          <Text style={styles.empty}>
            Nothing here yet. Scan an item ("An item, not worn") and add it to
            your wardrobe from its read.
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
            onPress={() => onOpenOutfit(item.outfit_id)}
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
                {item.note && item.note.trim().length > 0
                  ? item.note
                  : sentenceCase(item.category)}
              </Text>
              <Text style={styles.rowMeta}>
                {sentenceCase(item.category)} · {sentenceCase(item.pattern)}
              </Text>
            </View>

            <Button
              variant="quiet"
              label="Remove"
              onPress={() => void remove(item.item_id)}
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
  backLink: { ...type.body, color: colors.accent, fontWeight: '600', marginBottom: space.sm },
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
