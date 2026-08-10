/**
 * Shared UI primitives — spec §2.6.
 *
 * Editorial restraint: Ink and Bone carry the screen, Amber appears only on
 * the primary action and on active state.
 */
import React from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
  ViewStyle,
} from 'react-native';

import { colors, radius, space, type } from '../theme';

// --- Button ----------------------------------------------------------------
interface ButtonProps {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'quiet';
  disabled?: boolean;
  busy?: boolean;
  style?: ViewStyle;
}

export function Button({
  label,
  onPress,
  variant = 'primary',
  disabled = false,
  busy = false,
  style,
}: ButtonProps): React.ReactElement {
  const inactive = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled: inactive, busy }}
      onPress={onPress}
      disabled={inactive}
      style={({ pressed }) => [
        styles.button,
        variant === 'primary' && styles.buttonPrimary,
        variant === 'secondary' && styles.buttonSecondary,
        variant === 'quiet' && styles.buttonQuiet,
        pressed && styles.buttonPressed,
        inactive && styles.buttonDisabled,
        style,
      ]}
    >
      {busy ? (
        <ActivityIndicator color={variant === 'primary' ? colors.onAccent : colors.text} />
      ) : (
        <Text
          style={[
            styles.buttonLabel,
            variant === 'quiet' && styles.buttonLabelQuiet,
          ]}
        >
          {label}
        </Text>
      )}
    </Pressable>
  );
}

// --- Chip (occasion select) ------------------------------------------------
interface ChipProps {
  label: string;
  selected: boolean;
  onPress: () => void;
}

export function Chip({ label, selected, onPress }: ChipProps): React.ReactElement {
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={({ pressed }) => [
        styles.chip,
        selected && styles.chipSelected,
        pressed && styles.buttonPressed,
      ]}
    >
      <Text style={[styles.chipLabel, selected && styles.chipLabelSelected]}>
        {label}
      </Text>
    </Pressable>
  );
}

// --- Section label ---------------------------------------------------------
export function SectionLabel({ children }: { children: string }): React.ReactElement {
  return <Text style={styles.sectionLabel}>{children}</Text>;
}

// --- Skeleton (§4.1 pending state) ----------------------------------------
export function SkeletonLine({ width = '100%' }: { width?: number | string }): React.ReactElement {
  return <View style={[styles.skeleton, { width } as ViewStyle]} />;
}

export function Divider(): React.ReactElement {
  return <View style={styles.divider} />;
}

// --- Colour swatch row -----------------------------------------------------
export function Swatches({ hexes }: { hexes: string[] }): React.ReactElement | null {
  if (hexes.length === 0) return null;
  return (
    <View style={styles.swatchRow}>
      {hexes.map((hex, index) => (
        <View
          key={`${hex}-${index}`}
          style={[styles.swatch, { backgroundColor: hex }]}
          accessibilityLabel={`Colour ${hex}`}
        />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  button: {
    minHeight: 52,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.lg,
  },
  buttonPrimary: { backgroundColor: colors.accent },
  buttonSecondary: {
    backgroundColor: 'transparent',
    borderWidth: 1,
    borderColor: colors.border,
  },
  buttonQuiet: { backgroundColor: 'transparent', minHeight: 40 },
  buttonPressed: { opacity: 0.7 },
  buttonDisabled: { opacity: 0.45 },
  buttonLabel: { ...type.bodyMedium, color: colors.text },
  buttonLabelQuiet: { color: colors.textMuted },

  chip: {
    paddingVertical: space.sm,
    paddingHorizontal: space.md,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    marginRight: space.sm,
    marginBottom: space.sm,
  },
  chipSelected: { borderColor: colors.accent, backgroundColor: '#FAF2E1' },
  chipLabel: { ...type.meta, color: colors.textMuted },
  chipLabelSelected: { color: colors.text },

  sectionLabel: {
    ...type.sectionLabel,
    color: colors.textMuted,
    textTransform: 'uppercase',
    marginBottom: space.sm,
  },

  skeleton: {
    height: 14,
    borderRadius: radius.sm,
    backgroundColor: colors.border,
    marginBottom: space.sm,
  },

  divider: {
    height: 1,
    backgroundColor: colors.border,
    marginVertical: space.lg,
  },

  swatchRow: { flexDirection: 'row', marginTop: space.sm },
  swatch: {
    width: 22,
    height: 22,
    borderRadius: radius.sm,
    marginRight: space.xs,
    borderWidth: 1,
    borderColor: colors.border,
  },
});
