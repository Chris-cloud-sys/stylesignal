/**
 * Scan history — spec §6.3.
 *
 * A photo grid, not a tall list of rows — the standard pattern for
 * browsing a growing collection of your own photos (Photos, Instagram's
 * own profile grid). Occasion/date/status text and the per-row Delete
 * button moved off the grid entirely: metadata lives on the detail
 * screen a tap away, and delete is a long-press-to-select gesture
 * instead of a tap target sitting on every cell.
 */
import { Ionicons } from '@expo/vector-icons';
import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Dimensions,
  FlatList,
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { absoluteMediaUrl, deleteOutfit, fetchHistory } from '../api/client';
import type { OutfitListItem } from '../api/types';
import { colors, radius, space, type } from '../theme';

interface Props {
  onOpen: (outfitId: string) => void;
}

const COLUMNS = 3;
const GRID_PADDING = space.md;
const GRID_GAP = space.xs;
const { width: SCREEN_WIDTH } = Dimensions.get('window');
const CELL_SIZE = (SCREEN_WIDTH - GRID_PADDING * 2 - GRID_GAP * (COLUMNS - 1)) / COLUMNS;

export function HistoryScreen({ onOpen }: Props): React.ReactElement {
  const [items, setItems] = useState<OutfitListItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const selecting = selected.size > 0;

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

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <FlatList
        data={items}
        keyExtractor={(item) => item.outfit_id}
        numColumns={COLUMNS}
        contentContainerStyle={styles.grid}
        columnWrapperStyle={styles.gridRow}
        ListEmptyComponent={
          <Text style={styles.empty}>
            Nothing here yet. Your scans will collect on this screen.
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
          loadingMore ? <ActivityIndicator color={colors.textMuted} style={styles.footerSpinner} /> : null
        }
        renderItem={({ item }) => {
          const isSelected = selected.has(item.outfit_id);
          return (
            <Pressable
              style={styles.cell}
              onPress={() => (selecting ? toggleSelect(item.outfit_id) : onOpen(item.outfit_id))}
              onLongPress={() => toggleSelect(item.outfit_id)}
              accessibilityRole="button"
              accessibilityLabel={
                item.occasion ? `${item.occasion} scan` : 'Scan with no occasion tagged'
              }
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

              {item.status !== 'complete' ? (
                <View style={styles.statusBadge}>
                  {item.status === 'failed' ? (
                    <Ionicons name="alert-circle" size={14} color={colors.systemError} />
                  ) : (
                    <ActivityIndicator size="small" color={colors.onPhoto} />
                  )}
                </View>
              ) : null}

              {isSelected ? (
                <View style={styles.selectedScrim}>
                  <Ionicons name="checkmark-circle" size={22} color={colors.accent} />
                </View>
              ) : selecting ? (
                <View style={styles.unselectedMark} />
              ) : null}
            </Pressable>
          );
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
  grid: { paddingHorizontal: GRID_PADDING, paddingBottom: space.xxl },
  gridRow: { gap: GRID_GAP, marginBottom: GRID_GAP },
  empty: { ...type.body, color: colors.textMuted, marginTop: space.xl, paddingHorizontal: space.md },
  error: {
    ...type.meta,
    color: colors.systemError,
    paddingHorizontal: space.lg,
    marginBottom: space.sm,
  },
  footerSpinner: { marginVertical: space.md },
  cell: { width: CELL_SIZE, height: CELL_SIZE },
  thumb: {
    width: '100%',
    height: '100%',
    borderRadius: radius.sm,
    backgroundColor: colors.surface,
  },
  thumbPlaceholder: { borderWidth: 1, borderColor: colors.border },
  statusBadge: {
    position: 'absolute',
    top: 4,
    right: 4,
    width: 20,
    height: 20,
    borderRadius: radius.pill,
    backgroundColor: 'rgba(0,0,0,0.55)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  selectedScrim: {
    ...StyleSheet.absoluteFillObject,
    borderRadius: radius.sm,
    backgroundColor: 'rgba(0,0,0,0.35)',
    alignItems: 'flex-end',
    justifyContent: 'flex-start',
    padding: 4,
  },
  unselectedMark: {
    position: 'absolute',
    top: 4,
    right: 4,
    width: 20,
    height: 20,
    borderRadius: radius.pill,
    borderWidth: 1.5,
    borderColor: colors.background,
    backgroundColor: 'rgba(0,0,0,0.2)',
  },
});
