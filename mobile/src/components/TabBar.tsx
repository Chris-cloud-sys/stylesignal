/** Persistent bottom navigation — Home, Favorites, Community, History, Profile. */
import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, space, type, weight } from '../theme';

export type TabName = 'capture' | 'favorites' | 'feed' | 'history' | 'profile';

const TABS: Array<{ name: TabName; label: string; icon: keyof typeof Ionicons.glyphMap; iconActive: keyof typeof Ionicons.glyphMap }> = [
  { name: 'capture', label: 'Home', icon: 'home-outline', iconActive: 'home' },
  { name: 'favorites', label: 'Favorites', icon: 'heart-outline', iconActive: 'heart' },
  { name: 'feed', label: 'Community', icon: 'people-outline', iconActive: 'people' },
  { name: 'history', label: 'History', icon: 'time-outline', iconActive: 'time' },
  { name: 'profile', label: 'Profile', icon: 'person-circle-outline', iconActive: 'person-circle' },
];

interface Props {
  active: TabName;
  onSelect: (tab: TabName) => void;
}

export function TabBar({ active, onSelect }: Props): React.ReactElement {
  const insets = useSafeAreaInsets();
  return (
    <View style={[styles.bar, { paddingBottom: Math.max(insets.bottom, space.xs) }]}>
      {TABS.map((tab) => {
        const selected = tab.name === active;
        const tint = selected ? colors.accent : colors.textMuted;
        return (
          <Pressable
            key={tab.name}
            onPress={() => onSelect(tab.name)}
            style={styles.tab}
            accessibilityRole="button"
            accessibilityState={{ selected }}
            accessibilityLabel={tab.label}
          >
            <Ionicons name={selected ? tab.iconActive : tab.icon} size={22} color={tint} />
            <Text style={[styles.label, { color: tint }, selected && styles.labelActive]}>
              {tab.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.surface,
    paddingTop: space.sm,
  },
  tab: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: space.xs,
  },
  label: { ...type.meta, fontSize: 11, marginTop: 2 },
  labelActive: { fontWeight: weight.medium },
});
