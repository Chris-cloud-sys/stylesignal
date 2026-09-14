/**
 * Shared 3-column photo grid — SPEC+ (docs/spec-deviations.md). Extracted
 * after the same row-list-of-thumbnails pattern (small thumbnail + text +
 * an always-visible "Remove" button on every row) showed up nearly
 * identically in History, Favorites, Wardrobe, and a member's public
 * profile. Not used by the Community feed — those cards hold a 5-point
 * rating form per outfit, which a small grid cell has no room for; that's
 * a fundamentally different interaction, not a photo browse.
 *
 * Selection (long-press to enter, tap to toggle, a caller-supplied delete
 * action) is optional — pass `onLongPress`/`isSelected`/`selecting` only
 * on a screen where the caller can actually remove something (their own
 * History, Favorites, Wardrobe). A read-only grid (someone else's public
 * profile) just omits them.
 */
import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import {
  ActivityIndicator,
  Dimensions,
  FlatList,
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { colors, radius, space, type } from '../theme';

const COLUMNS = 3;
const GRID_PADDING = space.md;
const GRID_GAP = space.xs;
const { width: SCREEN_WIDTH } = Dimensions.get('window');
export const PHOTO_GRID_CELL_SIZE =
  (SCREEN_WIDTH - GRID_PADDING * 2 - GRID_GAP * (COLUMNS - 1)) / COLUMNS;

export interface PhotoGridProps<T> {
  data: T[];
  keyExtractor: (item: T) => string;
  getThumbUrl: (item: T) => string | null | undefined;
  onPress: (item: T) => void;
  accessibilityLabel?: (item: T) => string;
  /** Small top-right overlay per cell — e.g. a processing/failed badge. */
  renderBadge?: (item: T) => React.ReactNode;
  /** Omit all three together for a read-only grid with no select/delete. */
  onLongPress?: (item: T) => void;
  isSelected?: (item: T) => boolean;
  selecting?: boolean;
  emptyText: string;
  ListHeaderComponent?: React.ReactElement;
  cursor?: string | null;
  loadingMore?: boolean;
  onEndReached?: () => void;
}

export function PhotoGrid<T>({
  data,
  keyExtractor,
  getThumbUrl,
  onPress,
  accessibilityLabel,
  renderBadge,
  onLongPress,
  isSelected,
  selecting,
  emptyText,
  ListHeaderComponent,
  cursor,
  loadingMore,
  onEndReached,
}: PhotoGridProps<T>): React.ReactElement {
  return (
    <FlatList
      data={data}
      keyExtractor={keyExtractor}
      numColumns={COLUMNS}
      contentContainerStyle={styles.grid}
      columnWrapperStyle={styles.gridRow}
      ListHeaderComponent={ListHeaderComponent}
      ListEmptyComponent={<Text style={styles.empty}>{emptyText}</Text>}
      onEndReachedThreshold={0.4}
      onEndReached={() => {
        if (cursor && !loadingMore) onEndReached?.();
      }}
      ListFooterComponent={
        loadingMore ? <ActivityIndicator color={colors.textMuted} style={styles.footerSpinner} /> : null
      }
      renderItem={({ item }) => {
        const thumbUrl = getThumbUrl(item);
        const selected = isSelected?.(item) ?? false;
        return (
          <Pressable
            style={styles.cell}
            onPress={() => onPress(item)}
            onLongPress={onLongPress ? () => onLongPress(item) : undefined}
            accessibilityRole="button"
            accessibilityLabel={accessibilityLabel?.(item)}
          >
            {thumbUrl ? (
              <Image source={{ uri: thumbUrl }} style={styles.thumb} resizeMode="cover" />
            ) : (
              <View style={[styles.thumb, styles.thumbPlaceholder]} />
            )}

            {renderBadge?.(item)}

            {selected ? (
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
  );
}

const styles = StyleSheet.create({
  grid: { paddingHorizontal: GRID_PADDING, paddingBottom: space.xxl },
  gridRow: { gap: GRID_GAP, marginBottom: GRID_GAP },
  empty: { ...type.body, color: colors.textMuted, marginTop: space.xl, paddingHorizontal: space.md },
  footerSpinner: { marginVertical: space.md },
  cell: { width: PHOTO_GRID_CELL_SIZE, height: PHOTO_GRID_CELL_SIZE },
  thumb: {
    width: '100%',
    height: '100%',
    borderRadius: radius.sm,
    backgroundColor: colors.surface,
  },
  thumbPlaceholder: { borderWidth: 1, borderColor: colors.border },
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
    borderColor: colors.onPhoto,
    backgroundColor: 'rgba(0,0,0,0.2)',
  },
});

export function GridStatusBadge({ status }: { status: 'pending' | 'processing' | 'failed' | 'complete' }): React.ReactElement | null {
  if (status === 'complete') return null;
  return (
    <View style={badgeStyles.badge}>
      {status === 'failed' ? (
        <Ionicons name="alert-circle" size={14} color={colors.systemError} />
      ) : (
        <ActivityIndicator size="small" color={colors.onPhoto} />
      )}
    </View>
  );
}

const badgeStyles = StyleSheet.create({
  badge: {
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
});
