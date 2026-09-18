/**
 * A genuinely browsable, swipeable feed of outfit reads — SPEC+
 * (docs/spec-deviations.md #42). Reuses the same card shape (photo,
 * verdict headline, TikTok-style rail) Community's own Browse mode
 * (FeedScreen.tsx) already established, so History/Favorites/a member's
 * profile grid can all open the identical experience instead of a second,
 * parallel one — only the data source (and whether an item is the
 * viewer's own) differs.
 *
 * A full-screen destination (App.tsx's `browse` Screen entry), not a modal
 * over the grid — consistent with how every other drill-in (Wardrobe,
 * Insights, a member's profile) already works in this hand-rolled
 * switcher. Backing out returns to the grid screen that opened it, which
 * remounts fresh — the grid itself was never left running underneath.
 */
import { Ionicons } from '@expo/vector-icons';
import React, { useEffect, useRef, useState } from 'react';
import { FlatList, Image, Pressable, StyleSheet, Text, View } from 'react-native';

import {
  absoluteMediaUrl,
  favoriteOutfit,
  fetchMe,
  followUser,
  likeOutfit,
  unfavoriteOutfit,
  unfollowUser,
  unlikeOutfit,
} from '../api/client';
import type { OutfitListItem } from '../api/types';
import { CommentSheet } from './CommentSheet';
import { FloatingBackButton } from './FloatingBackButton';
import { Avatar } from './primitives';
import { ShareOutfitAction } from './ShareOutfitAction';
import { colors, radius, sentenceCase, space, type } from '../theme';

interface Props {
  items: OutfitListItem[];
  initialIndex: number;
  onBack: () => void;
  onOpenProfile: (userId: string) => void;
}

export function BrowseFeed({ items, initialIndex, onBack, onOpenProfile }: Props): React.ReactElement {
  const [viewerId, setViewerId] = useState<string | null>(null);
  const listRef = useRef<FlatList<OutfitListItem>>(null);

  useEffect(() => {
    fetchMe()
      .then((me) => setViewerId(me.user.id))
      .catch(() => undefined);
  }, []);

  // SPEC+ (docs/spec-deviations.md #46) — the real cause of "opens to a
  // blank white screen, the photo only appears after scrolling": passing
  // initialScrollIndex jumps the scroll *offset* to an estimate computed
  // before any real layout exists (card height varies with rail/verdict
  // length, so there's no getItemLayout to give FlatList an exact one) —
  // the jump lands correctly, but the cell at that position hasn't
  // actually been measured/rendered yet, so it paints blank until a
  // manual scroll forces FlatList to remeasure. Fixed by letting the list
  // mount and render normally from the top first (no initialScrollIndex
  // at all), then scrolling to the tapped item on the next tick, by
  // which point real cells exist to land on.
  useEffect(() => {
    if (initialIndex <= 0) return;
    const id = setTimeout(() => {
      listRef.current?.scrollToIndex({ index: initialIndex, animated: false });
    }, 50);
    return () => clearTimeout(id);
  }, [initialIndex]);

  return (
    <View style={styles.flex}>
      <View style={styles.header}>
        <Text style={styles.title}>Browse</Text>
      </View>

      <FlatList
        ref={listRef}
        data={items}
        keyExtractor={(item) => item.outfit_id}
        contentContainerStyle={styles.list}
        keyboardShouldPersistTaps="handled"
        onScrollToIndexFailed={(info) => {
          // RN's own documented recovery for this: land close via the
          // estimated offset first (cheap, always available), then retry
          // the precise index once that scroll has given FlatList a
          // fresh set of rendered cells to measure from.
          listRef.current?.scrollToOffset({
            offset: info.averageItemLength * info.index,
            animated: false,
          });
          setTimeout(() => {
            listRef.current?.scrollToIndex({ index: info.index, animated: false });
          }, 100);
        }}
        renderItem={({ item }) => (
          <BrowseCard
            item={item}
            isOwn={viewerId != null && item.owner_id === viewerId}
            onOpenProfile={onOpenProfile}
          />
        )}
      />

      <FloatingBackButton onPress={onBack} />
    </View>
  );
}

function BrowseCard({
  item,
  isOwn,
  onOpenProfile,
}: {
  item: OutfitListItem;
  isOwn: boolean;
  onOpenProfile: (userId: string) => void;
}): React.ReactElement {
  const [liked, setLiked] = useState(item.liked_by_me);
  const [likeCount, setLikeCount] = useState(item.like_count ?? 0);
  const [likeBusy, setLikeBusy] = useState(false);
  const [favorited, setFavorited] = useState(item.favorited_by_me);
  const [favoriteBusy, setFavoriteBusy] = useState(false);
  const [commentCount, setCommentCount] = useState(item.comment_count);
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [following, setFollowing] = useState(item.following_owner);
  const [followBusy, setFollowBusy] = useState(false);
  const thumb = absoluteMediaUrl(item.thumb_url);

  // Same rule as Community's FeedCard: liking is others-only
  // (_likeable_outfit blocks self-likes server-side too), so an own item
  // never shows the toggle at all rather than showing one that would fail.
  const toggleLike = async (): Promise<void> => {
    if (likeBusy || isOwn) return;
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

  // Unlike liking, favoriting your own outfit is allowed (a personal
  // bookmark, no community-visibility implication) — same as ResultScreen.
  const toggleFavorite = async (): Promise<void> => {
    if (favoriteBusy) return;
    const wasFavorited = favorited;
    setFavoriteBusy(true);
    setFavorited(!wasFavorited);
    try {
      const response = wasFavorited
        ? await unfavoriteOutfit(item.outfit_id)
        : await favoriteOutfit(item.outfit_id);
      setFavorited(response.favorited);
    } catch {
      setFavorited(wasFavorited);
    } finally {
      setFavoriteBusy(false);
    }
  };

  const toggleFollow = async (): Promise<void> => {
    if (followBusy || isOwn || !item.owner_id) return;
    const wasFollowing = following;
    setFollowBusy(true);
    setFollowing(!wasFollowing);
    try {
      const response = wasFollowing
        ? await unfollowUser(item.owner_id)
        : await followUser(item.owner_id);
      setFollowing(response.following);
    } catch {
      setFollowing(wasFollowing);
    } finally {
      setFollowBusy(false);
    }
  };

  return (
    <View style={styles.card}>
      <View style={styles.imageWrap}>
        {thumb ? (
          <Image source={{ uri: thumb }} style={styles.cardImage} resizeMode="cover" />
        ) : (
          <View style={[styles.cardImage, styles.cardImagePlaceholder]} />
        )}

        <View style={styles.rail}>
          {!isOwn && item.owner_id ? (
            <Pressable
              onPress={() => onOpenProfile(item.owner_id!)}
              style={styles.railAvatarWrap}
              accessibilityRole="button"
              accessibilityLabel={`Open ${item.owner_display_name}'s profile`}
            >
              <View style={styles.railAvatarBorder}>
                <Avatar name={item.owner_display_name ?? '?'} uri={item.owner_avatar_url} size={36} />
              </View>
              {!following ? (
                <Pressable
                  onPress={() => void toggleFollow()}
                  style={styles.railFollowBadge}
                  accessibilityRole="button"
                  accessibilityLabel={`Follow ${item.owner_display_name}`}
                  hitSlop={6}
                >
                  <Ionicons name="add" size={12} color={colors.onAccent} />
                </Pressable>
              ) : null}
            </Pressable>
          ) : null}

          {!isOwn ? (
            <Pressable
              onPress={() => void toggleLike()}
              style={styles.railAction}
              accessibilityRole="button"
              accessibilityLabel={liked ? 'Unlike this outfit' : 'Like this outfit'}
            >
              <Text style={[styles.railLikeGlyph, liked && styles.railLikeGlyphActive]}>
                {liked ? '♥' : '♡'}
              </Text>
              <Text style={styles.railCount}>{likeCount}</Text>
            </Pressable>
          ) : likeCount > 0 ? (
            <View style={styles.railAction}>
              <Text style={styles.railLikeGlyph}>♥</Text>
              <Text style={styles.railCount}>{likeCount}</Text>
            </View>
          ) : null}

          <Pressable
            onPress={() => setCommentsOpen(true)}
            style={styles.railAction}
            accessibilityRole="button"
            accessibilityLabel="View comments"
          >
            <Ionicons name="chatbubble-outline" size={24} color={colors.onPhoto} />
            <Text style={styles.railCount}>{commentCount}</Text>
          </Pressable>

          <Pressable
            onPress={() => void toggleFavorite()}
            style={styles.railAction}
            accessibilityRole="button"
            accessibilityLabel={favorited ? 'Remove from favorites' : 'Add to favorites'}
          >
            <Ionicons
              name={favorited ? 'bookmark' : 'bookmark-outline'}
              size={24}
              color={favorited ? colors.accent : colors.onPhoto}
            />
          </Pressable>

          <ShareOutfitAction
            outfitId={item.outfit_id}
            occasion={item.occasion}
            thumbUri={thumb}
            style={styles.railAction}
          />
        </View>
      </View>

      {item.verdict_phrase ? <Text style={styles.cardVerdict}>{item.verdict_phrase}</Text> : null}
      {item.occasion ? (
        <Text style={styles.cardOccasion}>Occasion: {sentenceCase(item.occasion)}</Text>
      ) : null}

      <CommentSheet
        outfitId={item.outfit_id}
        visible={commentsOpen}
        onClose={() => setCommentsOpen(false)}
        onCountChange={(delta) => setCommentCount((count) => Math.max(0, count + delta))}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.background },
  header: {
    paddingHorizontal: space.lg,
    paddingTop: space.lg,
    paddingBottom: space.md,
  },
  title: { ...type.title, color: colors.text },
  list: { paddingHorizontal: space.lg, paddingBottom: space.xxl },

  card: {
    marginBottom: space.xl,
    paddingBottom: space.lg,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  imageWrap: { marginBottom: space.sm },
  cardImage: {
    width: '100%',
    aspectRatio: 3 / 4,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
  },
  cardImagePlaceholder: { borderWidth: 1, borderColor: colors.border },
  cardVerdict: { ...type.bodyMedium, color: colors.text, marginTop: space.md },
  cardOccasion: { ...type.meta, color: colors.textMuted, marginTop: 2 },

  rail: {
    position: 'absolute',
    right: space.sm,
    bottom: space.md,
    alignItems: 'center',
    gap: space.md,
  },
  railAvatarWrap: { alignItems: 'center', marginBottom: space.xs },
  railAvatarBorder: {
    borderRadius: radius.pill,
    borderWidth: 1.5,
    borderColor: colors.onPhoto,
    overflow: 'hidden',
  },
  railFollowBadge: {
    position: 'absolute',
    bottom: -6,
    width: 18,
    height: 18,
    borderRadius: radius.pill,
    backgroundColor: colors.accent,
    borderWidth: 1.5,
    borderColor: colors.onPhoto,
    alignItems: 'center',
    justifyContent: 'center',
  },
  railAction: { alignItems: 'center' },
  railLikeGlyph: { fontSize: 26, color: colors.onPhoto, lineHeight: 28 },
  railLikeGlyphActive: { color: colors.accent },
  railCount: {
    ...type.meta,
    color: colors.onPhoto,
    marginTop: 2,
    textShadowColor: 'rgba(0,0,0,0.4)',
    textShadowRadius: 3,
  },
});
