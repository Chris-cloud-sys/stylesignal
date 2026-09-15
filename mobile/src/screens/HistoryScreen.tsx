/** Scan history — spec §6.3. A photo grid (see components/PhotoGrid.tsx). */
import { Ionicons } from '@expo/vector-icons';
import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { absoluteMediaUrl, deleteOutfit, fetchHistory } from '../api/client';
import type { OutfitListItem } from '../api/types';
import { GridStatusBadge, PhotoGrid } from '../components/PhotoGrid';
import { type GridMode, ReadBrowseToggle } from '../components/ReadBrowseToggle';
import { colors, space, type } from '../theme';

interface Props {
  onOpen: (outfitId: string) => void;
  /** SPEC+ — genuinely browsable History (docs/spec-deviations.md #42). */
  onBrowse: (items: OutfitListItem[], initialIndex: number) => void;
}

export function HistoryScreen({ onOpen, onBrowse }: Props): React.ReactElement {
  const [items, setItems] = useState<OutfitListItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const selecting = selected.size > 0;
  const [mode, setMode] = useState<GridMode>('read');

  const load = useCallback(async (nextCursor?: string | null): Promise<void> => {
    try {
      const page = await fetchHistory(nextCursor);
      setItems((existing) =>
        nextCursor ? [...existing, ...page.items] : page.items,
      );
      setCursor(page.cursor ?? null);
      setError(null);
    } catch {
      setError('Could not load your history.');
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

  // SPEC+ — genuinely browsable History (docs/spec-deviations.md #42,
  // round 2). The persistent toggle above the grid picks the mode; tapping
  // a photo just does that mode's action immediately, no per-tap picker.
  // Browse still needs a completed scan (the card format needs the
  // verdict/rail a pending or failed scan doesn't have) — one without
  // falls back to Read regardless of the toggle.
  const openItem = (item: OutfitListItem): void => {
    if (mode === 'browse' && item.status === 'complete') {
      onBrowse(items, items.findIndex((i) => i.outfit_id === item.outfit_id));
    } else {
      onOpen(item.outfit_id);
    }
  };

  const deleteSelected = (): void => {
    const ids = Array.from(selected);
    Alert.alert(
      ids.length === 1 ? 'Delete this scan?' : `Delete ${ids.length} scans?`,
      'This cannot be undone.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: () => {
            setItems((existing) => existing.filter((item) => !selected.has(item.outfit_id)));
            setSelected(new Set());
            Promise.all(ids.map((id) => deleteOutfit(id))).catch(() => void load());
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
              onPress={deleteSelected}
              accessibilityRole="button"
              accessibilityLabel="Delete selected scans"
              hitSlop={8}
            >
              <Ionicons name="trash-outline" size={22} color={colors.systemError} />
            </Pressable>
          </>
        ) : (
          <Text style={styles.title}>History</Text>
        )}
      </View>

      {!selecting ? <ReadBrowseToggle mode={mode} onChange={setMode} /> : null}

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
          item.occasion ? `${item.occasion} scan` : 'Scan with no occasion tagged'
        }
        emptyText="Nothing here yet. Your scans will collect on this screen."
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
