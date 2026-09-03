/** Scan history — spec §6.3. */
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

import { absoluteMediaUrl, deleteOutfit, fetchHistory } from '../api/client';
import type { OutfitListItem } from '../api/types';
import { Button } from '../components/primitives';
import { colors, radius, sentenceCase, space, type } from '../theme';

interface Props {
  onOpen: (outfitId: string) => void;
  onBack: () => void;
}

export function HistoryScreen({ onOpen, onBack }: Props): React.ReactElement {
  const [items, setItems] = useState<OutfitListItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const remove = async (outfitId: string): Promise<void> => {
    setItems((existing) => existing.filter((item) => item.outfit_id !== outfitId));
    try {
      await deleteOutfit(outfitId);
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
        <Text style={styles.title}>History</Text>
        <Pressable onPress={onBack} accessibilityRole="button">
          <Text style={styles.headerLink}>Done</Text>
        </Pressable>
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <FlatList
        data={items}
        keyExtractor={(item) => item.outfit_id}
        contentContainerStyle={styles.list}
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
                {new Date(item.created_at).toLocaleDateString()} ·{' '}
                {statusWord(item.status)}
                {typeof item.like_count === 'number'
                  ? ` · ${item.like_count} ${item.like_count === 1 ? 'like' : 'likes'}`
                  : ''}
              </Text>
            </View>

            <Button
              variant="quiet"
              label="Delete"
              onPress={() => void remove(item.outfit_id)}
            />
          </Pressable>
        )}
      />
    </View>
  );
}

function statusWord(status: OutfitListItem['status']): string {
  switch (status) {
    case 'complete':
      return 'Read ready';
    case 'failed':
      return 'Did not finish';
    default:
      return 'Still reading';
  }
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
