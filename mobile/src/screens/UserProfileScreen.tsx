/** A member's public profile — SPEC+ (docs/spec-deviations.md). Follower/
 * following counts, a follow/unfollow action, and their public reads. */
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

import { absoluteMediaUrl, fetchUserProfile, followUser, unfollowUser } from '../api/client';
import type { OutfitListItem, UserProfile } from '../api/types';
import { Button } from '../components/primitives';
import { colors, radius, sentenceCase, space, type } from '../theme';

interface Props {
  userId: string;
  onBack: () => void;
  onOpenOutfit: (outfitId: string) => void;
}

export function UserProfileScreen({ userId, onBack, onOpenOutfit }: Props): React.ReactElement {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [items, setItems] = useState<OutfitListItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [followBusy, setFollowBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (): Promise<void> => {
    try {
      const result = await fetchUserProfile(userId);
      setProfile(result);
      setItems(result.outfits);
      setCursor(result.cursor ?? null);
      setError(null);
    } catch {
      setError('Could not load this profile.');
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    void load();
  }, [load]);

  const loadMore = async (): Promise<void> => {
    if (!cursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const result = await fetchUserProfile(userId, cursor);
      setItems((existing) => [...existing, ...result.outfits]);
      setCursor(result.cursor ?? null);
    } finally {
      setLoadingMore(false);
    }
  };

  const toggleFollow = async (): Promise<void> => {
    if (!profile || followBusy) return;
    const wasFollowing = profile.is_following;
    setFollowBusy(true);
    setProfile({
      ...profile,
      is_following: !wasFollowing,
      follower_count: profile.follower_count + (wasFollowing ? -1 : 1),
    });
    try {
      const response = wasFollowing ? await unfollowUser(userId) : await followUser(userId);
      setProfile((current) =>
        current
          ? { ...current, is_following: response.following, follower_count: response.follower_count }
          : current,
      );
    } catch {
      setProfile((current) =>
        current
          ? {
              ...current,
              is_following: wasFollowing,
              follower_count: current.follower_count + (wasFollowing ? 1 : -1),
            }
          : current,
      );
    } finally {
      setFollowBusy(false);
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
      </View>

      {error ? <Text style={styles.error}>{error}</Text> : null}

      {profile ? (
        <View style={styles.profileHead}>
          <Text style={styles.title}>{profile.display_name}</Text>
          <View style={styles.statsRow}>
            <Stat label="Reads" value={profile.outfit_count} />
            <Stat label="Followers" value={profile.follower_count} />
            <Stat label="Following" value={profile.following_count} />
          </View>
          {!profile.is_self ? (
            <Button
              variant={profile.is_following ? 'secondary' : 'primary'}
              label={profile.is_following ? 'Following' : 'Follow'}
              onPress={() => void toggleFollow()}
              busy={followBusy}
              style={styles.followButton}
            />
          ) : null}
        </View>
      ) : null}

      <FlatList
        data={items}
        keyExtractor={(item) => item.outfit_id}
        contentContainerStyle={styles.list}
        ListEmptyComponent={
          <Text style={styles.empty}>Nothing shared with the community yet.</Text>
        }
        onEndReachedThreshold={0.4}
        onEndReached={() => void loadMore()}
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
                {item.occasion ? sentenceCase(item.occasion) : 'No occasion tagged'}
              </Text>
              <Text style={styles.rowMeta}>
                {typeof item.like_count === 'number'
                  ? `${item.like_count} ${item.like_count === 1 ? 'like' : 'likes'}`
                  : ''}
              </Text>
            </View>
          </Pressable>
        )}
      />
    </View>
  );
}

function Stat({ label, value }: { label: string; value: number }): React.ReactElement {
  return (
    <View style={styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
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
  },
  backLink: { ...type.body, color: colors.accent, fontWeight: '600' },
  profileHead: {
    paddingHorizontal: space.lg,
    paddingTop: space.md,
    paddingBottom: space.lg,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  title: { ...type.title, color: colors.text },
  statsRow: { flexDirection: 'row', gap: space.xl, marginTop: space.md },
  stat: { alignItems: 'flex-start' },
  statValue: { ...type.bodyMedium, color: colors.text },
  statLabel: { ...type.meta, color: colors.textMuted, marginTop: 2 },
  followButton: { marginTop: space.md, alignSelf: 'flex-start' },
  list: { paddingHorizontal: space.lg, paddingBottom: space.xxl },
  empty: { ...type.body, color: colors.textMuted, marginTop: space.xl },
  error: {
    ...type.meta,
    color: colors.systemError,
    paddingHorizontal: space.lg,
    marginTop: space.sm,
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
