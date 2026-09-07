/** Profile — account info, quota, and sign out (moved off Home). */
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { fetchMe } from '../api/client';
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
  signOut: { marginTop: space.md },
});
