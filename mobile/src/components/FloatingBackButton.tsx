/**
 * A thumb-reachable "Back" — SPEC+ (docs/spec-deviations.md). The plain
 * top-left text link this replaces sat at the very top of the screen,
 * meaning a genuine stretch on a one-handed hold of a tall phone. Floating
 * and bottom-anchored instead, like a mini FAB, so it's reachable without
 * scrolling regardless of how far down the content goes — same idea as
 * why messaging apps put a reachable compose/back affordance low on the
 * screen rather than only in the header. Additive to (never a replacement
 * for) the hardware/gesture back App.tsx's BackHandler already wires up —
 * iOS has no hardware back button, so a visible on-screen affordance still
 * has to exist somewhere.
 */
import { Ionicons } from '@expo/vector-icons';
import React from 'react';
import { Pressable, StyleSheet } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, radius, space } from '../theme';

export function FloatingBackButton({ onPress }: { onPress: () => void }): React.ReactElement {
  const insets = useSafeAreaInsets();
  return (
    <Pressable
      onPress={onPress}
      style={[styles.button, { bottom: space.lg + insets.bottom }]}
      accessibilityRole="button"
      accessibilityLabel="Back"
      hitSlop={8}
    >
      <Ionicons name="chevron-back" size={24} color={colors.text} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    position: 'absolute',
    left: space.lg,
    width: 48,
    height: 48,
    borderRadius: radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    // A visible "this floats above the content" cue on both platforms.
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.15,
    shadowRadius: 6,
    elevation: 4,
  },
});
