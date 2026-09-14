/**
 * Wardrobe catalog — SPEC+ (docs/spec-deviations.md). A photo grid (see
 * components/PhotoGrid.tsx) — was a row list with an always-visible
 * "Remove" per row; long-press-to-select replaces that, same as History.
 *
 * A conscious reversal of the original "no wardrobe to catalogue" decision,
 * scoped narrowly: items are bootstrapped from "item, not worn" scans only,
 * reusing a capture flow that already exists rather than asking for a
 * second, dedicated cataloguing ritual.
 */
import { Ionicons } from '@expo/vector-icons';
import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { absoluteMediaUrl, fetchWardrobe, removeFromWardrobe } from '../api/client';
import type { WardrobeItem } from '../api/types';
import { PhotoGrid } from '../components/PhotoGrid';
import { colors, space, type } from '../theme';

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
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const selecting = selected.size > 0;

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

  const toggleSelect = (itemId: string): void => {
    setSelected((existing) => {
      const next = new Set(existing);
      if (next.has(itemId)) {
        next.delete(itemId);
      } else {
        next.add(itemId);
      }
      return next;
    });
  };

  const removeSelected = (): void => {
    const ids = Array.from(selected);
    Alert.alert(
      ids.length === 1 ? 'Remove this item?' : `Remove ${ids.length} items?`,
      'This only removes it from your wardrobe catalogue — the read itself stays in History.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Remove',
          style: 'destructive',
          onPress: () => {
            setItems((existing) => existing.filter((item) => !selected.has(item.item_id)));
            setSelected(new Set());
            Promise.all(ids.map((id) => removeFromWardrobe(id))).catch(() => void load());
          },
        },
      ],
    );
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
              accessibilityLabel="Remove selected items"
              hitSlop={8}
            >
              <Ionicons name="trash-outline" size={22} color={colors.systemError} />
            </Pressable>
          </>
        ) : (
          <>
            <Pressable onPress={onBack} accessibilityRole="button">
              <Text style={styles.headerLink}>Back</Text>
            </Pressable>
            <Text style={styles.title}>Wardrobe</Text>
            <View style={styles.headerSpacer} />
          </>
        )}
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <PhotoGrid
        data={items}
        keyExtractor={(item) => item.item_id}
        getThumbUrl={(item) => absoluteMediaUrl(item.thumb_url)}
        onPress={(item) => (selecting ? toggleSelect(item.item_id) : onOpenOutfit(item.outfit_id))}
        onLongPress={(item) => toggleSelect(item.item_id)}
        isSelected={(item) => selected.has(item.item_id)}
        selecting={selecting}
        accessibilityLabel={(item) => item.note?.trim() || item.category}
        emptyText='Nothing here yet. Scan an item ("An item, not worn") and add it to your wardrobe from its read.'
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
  headerSpacer: { width: 40 },
  title: { ...type.title, color: colors.text },
  headerLink: { ...type.body, color: colors.accent },
  error: {
    ...type.meta,
    color: colors.systemError,
    paddingHorizontal: space.lg,
    marginBottom: space.sm,
  },
});
