/** Profile — account info, quota, sharing default, and sign out (moved off Home). */
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Switch, Text, View } from 'react-native';

import { fetchMe, updateSharingDefault } from '../api/client';
import type { Me } from '../api/types';
import { Button, SectionLabel } from '../components/primitives';
import { colors, space, type } from '../theme';

interface Props {
  onSignOut: () => void;
  onOpenUpgrade: () => void;
}

export function ProfileScreen({ onSignOut, onOpenUpgrade }: Props): React.ReactElement {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [sharingBusy, setSharingBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void fetchMe()
      .then((result) => {
        if (!cancelled) setMe(result);
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

  return (
    <View style={styles.flex}>
      <View style={styles.header}>
        <Text style={styles.title}>Profile</Text>
      </View>

      {loading ? (
        <ActivityIndicator color={colors.textMuted} style={styles.spinner} />
      ) : (
        <View style={styles.body}>
          {me ? (
            <View style={styles.block}>
              <SectionLabel>Account</SectionLabel>
              <Text style={styles.email}>{me.user.email}</Text>
              <Text style={styles.meta}>
                {me.user.plan === 'pro' ? 'Pro' : 'Free'} plan
              </Text>
            </View>
          ) : null}

          {me ? (
            <View style={styles.block}>
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
            <View style={styles.block}>
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

          <Button
            variant="quiet"
            label="Sign out"
            onPress={onSignOut}
            style={styles.signOut}
          />
        </View>
      )}
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
  body: { paddingHorizontal: space.lg },
  block: { marginBottom: space.lg },
  email: { ...type.bodyMedium, color: colors.text, marginTop: space.xs },
  meta: { ...type.body, color: colors.textMuted, marginTop: space.xs },
  upgradeButton: { marginTop: space.md, alignSelf: 'flex-start' },
  sharingRow: { flexDirection: 'row', alignItems: 'center' },
  sharingCopy: { flex: 1, paddingRight: space.md },
  sharingTitle: { ...type.bodyMedium, color: colors.text },
  signOut: { marginTop: space.md },
});
