/** Profile — account info, quota, sharing default, and sign out (moved off Home).
 * Redesigned into cards (was one long clustered column) and wrapped in a
 * ScrollView — without it, Sign Out silently fell off the bottom of the
 * screen with no way to reach it once the avatar row pushed content past
 * the visible height. */
import * as ImagePicker from 'expo-image-picker';
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, ScrollView, Share, StyleSheet, Switch, Text, View } from 'react-native';

import { fetchMe, fetchUserProfile, removeAvatar, updateSharingDefault, uploadAvatar } from '../api/client';
import type { Me } from '../api/types';
import { Avatar, Button, SectionLabel } from '../components/primitives';
import { colors, getThemePreference, radius, setThemePreference, space, type, weight } from '../theme';
import type { ThemePreference } from '../theme';

interface Props {
  onSignOut: () => void;
  onOpenUpgrade: () => void;
  /** SPEC+ — view your own profile the way another member sees it. */
  onOpenProfile: (userId: string) => void;
  /** SPEC+ — personal signal history (docs/spec-deviations.md). */
  onOpenInsights: () => void;
  /** SPEC+ — wardrobe catalog (docs/spec-deviations.md). */
  onOpenWardrobe: () => void;
}

export function ProfileScreen({
  onSignOut,
  onOpenUpgrade,
  onOpenProfile,
  onOpenInsights,
  onOpenWardrobe,
}: Props): React.ReactElement {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [sharingBusy, setSharingBusy] = useState(false);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const [followStats, setFollowStats] = useState<{
    follower_count: number;
    following_count: number;
  } | null>(null);
  const [themePreference, setThemePreferenceState] = useState<ThemePreference>(getThemePreference);
  const [themeBusy, setThemeBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void fetchMe()
      .then((result) => {
        if (cancelled) return;
        setMe(result);
        void fetchUserProfile(result.user.id).then((profile) => {
          if (!cancelled) {
            setFollowStats({
              follower_count: profile.follower_count,
              following_count: profile.following_count,
            });
          }
        });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleSharing = async (value: boolean): Promise<void> => {
    if (!me || sharingBusy) return;
    const previous = me.user.default_share_public;
    setSharingBusy(true);
    setMe({ ...me, user: { ...me.user, default_share_public: value } });
    try {
      const updated = await updateSharingDefault(value);
      setMe(updated);
    } catch {
      setMe((current) =>
        current ? { ...current, user: { ...current.user, default_share_public: previous } } : current,
      );
    } finally {
      setSharingBusy(false);
    }
  };

  const changeAvatar = async (): Promise<void> => {
    if (avatarBusy) return;
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert('Permission needed', 'StyleSignal needs photo access to set a profile picture.');
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      allowsEditing: true,
      aspect: [1, 1],
      quality: 0.9,
    });
    if (result.canceled || result.assets.length === 0) return;
    const asset = result.assets[0];
    if (!asset) return;

    setAvatarBusy(true);
    try {
      const updated = await uploadAvatar(asset.uri);
      setMe(updated);
    } catch {
      Alert.alert('Could not update your profile picture', 'Try again in a moment.');
    } finally {
      setAvatarBusy(false);
    }
  };

  const clearAvatar = async (): Promise<void> => {
    if (avatarBusy) return;
    setAvatarBusy(true);
    try {
      const updated = await removeAvatar();
      setMe(updated);
    } catch {
      Alert.alert('Could not remove your profile picture', 'Try again in a moment.');
    } finally {
      setAvatarBusy(false);
    }
  };

  // Applying this reloads the app almost immediately (see theme.ts's
  // module header for why) — no need to update local state after the
  // call succeeds, since this screen is about to be torn down and
  // rebuilt with the new colours anyway.
  const changeTheme = async (preference: ThemePreference): Promise<void> => {
    if (themeBusy || preference === themePreference) return;
    setThemeBusy(true);
    setThemePreferenceState(preference);
    try {
      await setThemePreference(preference);
    } catch {
      setThemeBusy(false);
      setThemePreferenceState(themePreference);
      Alert.alert('Could not switch appearance', 'Try again in a moment.');
    }
  };

  return (
    <View style={styles.flex}>
      <View style={styles.header}>
        <Text style={styles.title}>Profile</Text>
      </View>

      {loading ? (
        <ActivityIndicator color={colors.textMuted} style={styles.spinner} />
      ) : (
        <ScrollView contentContainerStyle={styles.body}>
          {me ? (
            <View style={styles.card}>
              <SectionLabel>Account</SectionLabel>
              <View style={styles.avatarRow}>
                <Avatar name={me.user.display_name || me.user.email} uri={me.user.avatar_url} size={64} />
                <View style={styles.avatarActions}>
                  {avatarBusy ? (
                    <ActivityIndicator color={colors.textMuted} />
                  ) : (
                    <>
                      <Button
                        variant="quiet"
                        label={me.user.avatar_url ? 'Change photo' : 'Add a photo'}
                        onPress={() => void changeAvatar()}
                        style={styles.avatarActionButton}
                      />
                      {me.user.avatar_url ? (
                        <Button
                          variant="quiet"
                          label="Remove"
                          onPress={() => void clearAvatar()}
                          style={styles.avatarActionButton}
                        />
                      ) : null}
                    </>
                  )}
                </View>
              </View>
              <Text style={styles.email}>{me.user.email}</Text>
              <Text style={styles.meta}>{me.user.plan === 'pro' ? 'Pro' : 'Free'} plan</Text>
            </View>
          ) : null}

          {me && followStats ? (
            <View style={styles.card}>
              <SectionLabel>Community</SectionLabel>
              <View style={styles.statsRow}>
                <Stat label="Followers" value={followStats.follower_count} />
                <Stat label="Following" value={followStats.following_count} />
              </View>
              <Button
                variant="secondary"
                label="View public profile"
                onPress={() => onOpenProfile(me.user.id)}
                style={styles.viewProfileButton}
              />
            </View>
          ) : null}

          {me ? (
            <View style={styles.card}>
              <SectionLabel>Invite a friend</SectionLabel>
              <Text style={styles.meta}>
                Share your code. You each get 2 bonus scans the moment they
                create an account with it.
              </Text>
              <View style={styles.referralRow}>
                <Text style={styles.referralCode}>{me.user.referral_code}</Text>
              </View>
              <Button
                variant="secondary"
                label="Share invite"
                onPress={() => void shareReferralCode(me.user.referral_code)}
                style={styles.linkButton}
              />
            </View>
          ) : null}

          {me ? (
            <View style={styles.card}>
              <SectionLabel>Scans</SectionLabel>
              <Text style={styles.meta}>
                {me.quota.scans_remaining === null
                  ? 'Unlimited this month'
                  : `${me.quota.scans_remaining} left this month`}
              </Text>
              {me.user.plan !== 'pro' ? (
                <Button
                  variant="secondary"
                  label="Upgrade to Pro"
                  onPress={onOpenUpgrade}
                  style={styles.upgradeButton}
                />
              ) : null}
            </View>
          ) : null}

          {me ? (
            <View style={styles.card}>
              <SectionLabel>Sharing</SectionLabel>
              <View style={styles.sharingRow}>
                <View style={styles.sharingCopy}>
                  <Text style={styles.sharingTitle}>Share for community feedback</Text>
                  <Text style={styles.meta}>
                    On by default. When on, new scans can be seen and rated
                    by other members. Applies to scans going forward — to
                    remove one already shared, delete it from History.
                  </Text>
                </View>
                <Switch
                  value={me.user.default_share_public}
                  onValueChange={(value) => void toggleSharing(value)}
                  trackColor={{ true: colors.accent, false: colors.border }}
                  thumbColor={colors.surface}
                />
              </View>
            </View>
          ) : null}

          <View style={styles.card}>
            <SectionLabel>Appearance</SectionLabel>
            <View style={styles.themeRow}>
              {(
                [
                  { value: 'system', label: 'System' },
                  { value: 'light', label: 'Light' },
                  { value: 'dark', label: 'Dark' },
                ] as const
              ).map((option) => {
                const selected = option.value === themePreference;
                return (
                  <Pressable
                    key={option.value}
                    onPress={() => void changeTheme(option.value)}
                    disabled={themeBusy}
                    style={[styles.themeOption, selected && styles.themeOptionSelected]}
                    accessibilityRole="button"
                    accessibilityState={{ selected }}
                  >
                    <Text style={[styles.themeOptionLabel, selected && styles.themeOptionLabelSelected]}>
                      {option.label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
            {themeBusy ? <ActivityIndicator color={colors.textMuted} style={styles.themeSpinner} /> : null}
          </View>

          <View style={styles.card}>
            <SectionLabel>More</SectionLabel>
            <Button
              variant="secondary"
              label="Wardrobe"
              onPress={onOpenWardrobe}
              style={styles.linkButton}
            />
            <Button
              variant="secondary"
              label="Your style, so far"
              onPress={onOpenInsights}
              style={styles.linkButton}
            />
          </View>

          <Button variant="quiet" label="Sign out" onPress={onSignOut} style={styles.signOut} />
        </ScrollView>
      )}
    </View>
  );
}

function shareReferralCode(code: string): void {
  // SPEC+ — referral deep link (docs/spec-deviations.md). Only opens
  // straight to a pre-filled signup for someone who already has the app
  // installed (App.tsx's Linking handler); StyleSignal isn't in the Play
  // Store yet, so this can't yet do the "tap it, install, land signed up"
  // flow for someone brand new — the code is still spelled out in the
  // message itself so it's usable either way.
  const link = `stylesignal://join?ref=${encodeURIComponent(code)}`;
  Share.share({
    message:
      `Come read your outfits on StyleSignal — no scores, just an honest ` +
      `description of how a look comes across. Use my code ${code} when you ` +
      `sign up and we each get 2 bonus scans: ${link}`,
  }).catch(() => {
    // User cancelled or the share sheet failed to open — nothing to recover.
  });
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
  header: {
    paddingHorizontal: space.lg,
    paddingTop: space.lg,
    paddingBottom: space.md,
  },
  title: { ...type.title, color: colors.text },
  spinner: { marginTop: space.xl },
  body: { paddingHorizontal: space.lg, paddingBottom: space.xxl },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: space.lg,
    marginBottom: space.lg,
  },
  avatarRow: { flexDirection: 'row', alignItems: 'center', gap: space.md, marginTop: space.sm },
  avatarActions: { flexDirection: 'row' },
  avatarActionButton: { paddingHorizontal: 0, marginRight: space.md },
  email: { ...type.bodyMedium, color: colors.text, marginTop: space.md },
  meta: { ...type.body, color: colors.textMuted, marginTop: space.xs },
  upgradeButton: { marginTop: space.md, alignSelf: 'flex-start' },
  statsRow: { flexDirection: 'row', gap: space.xl, marginTop: space.sm, marginBottom: space.md },
  stat: { alignItems: 'flex-start' },
  statValue: { ...type.title, color: colors.text },
  statLabel: { ...type.meta, color: colors.textMuted, marginTop: 2 },
  viewProfileButton: { alignSelf: 'flex-start' },
  referralRow: {
    backgroundColor: colors.badgeBackground,
    borderRadius: radius.md,
    paddingVertical: space.sm,
    paddingHorizontal: space.md,
    marginTop: space.sm,
    alignSelf: 'flex-start',
  },
  referralCode: {
    ...type.title,
    color: colors.accent,
    letterSpacing: 2,
  },
  sharingRow: { flexDirection: 'row', alignItems: 'center', marginTop: space.sm },
  sharingCopy: { flex: 1, paddingRight: space.md },
  sharingTitle: { ...type.bodyMedium, color: colors.text },
  linkButton: { marginTop: space.sm, alignSelf: 'stretch' },
  signOut: { marginTop: space.sm, marginBottom: space.lg },
  themeRow: {
    flexDirection: 'row',
    gap: space.sm,
    marginTop: space.sm,
  },
  themeOption: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: space.sm,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  themeOptionSelected: { borderColor: colors.accent, backgroundColor: colors.badgeBackground },
  themeOptionLabel: { ...type.body, color: colors.textMuted },
  themeOptionLabelSelected: { color: colors.accent, fontWeight: weight.medium },
  themeSpinner: { marginTop: space.md },
});
