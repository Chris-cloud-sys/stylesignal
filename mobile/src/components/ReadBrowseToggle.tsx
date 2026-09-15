/**
 * Persistent Read/Browse mode switch — SPEC+ (docs/spec-deviations.md #42,
 * round 2). Replaces the original per-tap "Open this scan" Alert picker,
 * which Chris found intrusive. Same segmented-control look already used by
 * Community's Rate/Browse toggle and Profile's Light/Dark/System selector
 * — flip it once, and every tap on the grid immediately does that mode's
 * action with zero interruption. Shared by History, Favorites, and a
 * member's profile grid, so the three don't carry three copies of the same
 * styles.
 */
import React from 'react';
import { Pressable, StyleSheet, Text, View, ViewStyle } from 'react-native';

import { colors, radius, space, type, weight } from '../theme';

export type GridMode = 'read' | 'browse';

export function ReadBrowseToggle({
  mode,
  onChange,
  style,
}: {
  mode: GridMode;
  onChange: (mode: GridMode) => void;
  /** Default padding assumes a bare placement (History/Favorites' own
   * un-padded header). A caller whose surrounding container already pads
   * horizontally (UserProfileScreen's grid-driven ListHeaderComponent)
   * should override it to 0 rather than double up. */
  style?: ViewStyle;
}): React.ReactElement {
  return (
    <View style={[styles.row, style]}>
      {(
        [
          { value: 'read', label: 'Read' },
          { value: 'browse', label: 'Browse' },
        ] as const
      ).map((option) => {
        const selected = option.value === mode;
        return (
          <Pressable
            key={option.value}
            onPress={() => onChange(option.value)}
            style={[styles.option, selected && styles.optionSelected]}
            accessibilityRole="button"
            accessibilityState={{ selected }}
          >
            <Text style={[styles.optionLabel, selected && styles.optionLabelSelected]}>
              {option.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    gap: space.sm,
    paddingHorizontal: space.lg,
    paddingBottom: space.md,
  },
  option: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: space.sm,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  optionSelected: { borderColor: colors.accent, backgroundColor: colors.badgeBackground },
  optionLabel: { ...type.body, color: colors.textMuted },
  optionLabelSelected: { color: colors.accent, fontWeight: weight.medium },
});
