/**
 * Shared UI primitives — spec §2.6.
 *
 * Editorial restraint: Ink and Bone carry the screen, Amber appears only on
 * the primary action and on active state.
 */
import React, { useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  ViewStyle,
} from 'react-native';

import { colors, radius, sentenceCase, space, type, weight } from '../theme';

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

// --- Password field (show/hide) ---------------------------------------------
interface PasswordFieldProps {
  value: string;
  onChangeText: (value: string) => void;
  placeholder: string;
  autoComplete?: 'new-password' | 'current-password' | 'off';
  style?: ViewStyle;
}

export function PasswordField({
  value,
  onChangeText,
  placeholder,
  autoComplete,
  style,
}: PasswordFieldProps): React.ReactElement {
  const [visible, setVisible] = useState(false);
  return (
    <View style={[styles.passwordField, style]}>
      <TextInput
        style={styles.passwordInput}
        placeholder={placeholder}
        placeholderTextColor={colors.textMuted}
        value={value}
        onChangeText={onChangeText}
        secureTextEntry={!visible}
        autoCapitalize="none"
        autoComplete={autoComplete}
      />
      <Pressable
        onPress={() => setVisible((current) => !current)}
        style={styles.passwordToggle}
        hitSlop={8}
        accessibilityRole="button"
        accessibilityLabel={visible ? 'Hide password' : 'Show password'}
      >
        {visible ? <EyeOpenGlyph /> : <EyeClosedGlyph />}
      </Pressable>
    </View>
  );
}

function EyeOpenGlyph(): React.ReactElement {
  return (
    <View style={styles.pwEyeOuter}>
      <View style={styles.pwEyePupil} />
    </View>
  );
}

function EyeClosedGlyph(): React.ReactElement {
  return <View style={styles.pwEyeClosed} />;
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

// --- Meter (§7.7 glanceable result screen) ----------------------------------
// §2.6 forbids colour ever delivering the verdict — that rule applies here
// just as much as to the long-form text, so the fill is always Amber at
// every level (§7.8). strong/partial/off is communicated only by fill
// length and the text label next to it, never by hue.
interface MeterProps {
  label: string;
  level: 'strong' | 'partial' | 'off';
  score: number;
}

const METER_LEVEL_LABEL: Record<MeterProps['level'], string> = {
  strong: 'Strong',
  partial: 'Partial',
  off: 'Off',
};

export function Meter({ label, level, score }: MeterProps): React.ReactElement {
  const pct = Math.max(0, Math.min(1, score)) * 100;
  return (
    <View style={styles.meter}>
      <View style={styles.meterHead}>
        <Text style={styles.meterLabel}>{label}</Text>
        <Text style={styles.meterLevel}>{METER_LEVEL_LABEL[level]}</Text>
      </View>
      <View style={styles.meterTrack}>
        <View style={[styles.meterFill, { width: `${pct}%` } as ViewStyle]} />
      </View>
    </View>
  );
}

// --- Disclosure ("See full read") -------------------------------------------
interface DisclosureProps {
  label: string;
  children: React.ReactNode;
}

export function Disclosure({ label, children }: DisclosureProps): React.ReactElement {
  const [expanded, setExpanded] = useState(false);
  return (
    <View>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ expanded }}
        onPress={() => setExpanded((value) => !value)}
        style={({ pressed }) => [styles.disclosureHead, pressed && styles.buttonPressed]}
      >
        <Text style={styles.disclosureLabel}>{label}</Text>
        <Text style={styles.disclosureGlyph}>{expanded ? '−' : '+'}</Text>
      </Pressable>
      {expanded ? <View style={styles.disclosureBody}>{children}</View> : null}
    </View>
  );
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

// --- Icon badges (§7.8 "quick reads get an icon + rhythm") -----------------
// Plain View/StyleSheet geometry, not SVG line art — react-native-svg would
// need a new native module in the dev client build. A simple, distinct glyph
// per dimension in an amber-tinted circle carries the rhythm the spec asks
// for without that rebuild; swap for real line icons later if it's worth
// the extra build cycle.
export type QuickReadDimension = string;

const DIMENSION_GLYPH: Record<string, React.FC> = {
  colour: ColourGlyph,
  color: ColourGlyph,
  formality: FormalityGlyph,
  proportion: RulerGlyph,
  fit: RulerGlyph,
  texture: TextureGlyph,
  pattern: TextureGlyph,
};

// The backend's quick_reads dimension enum (colour, formality, proportion,
// pattern, texture, fit — see vlm.py's _QUICK_READ_DIMENSIONS) is finer-
// grained than the four the icon rhythm above actually distinguishes:
// proportion/fit share a glyph, pattern/texture share a glyph. The label
// has to collapse the same way, or a "proportion"-tagged read shows the
// ruler icon next to the text "PROPORTION" while an near-identical
// "fit"-tagged read shows the same icon next to "FIT" — same rhythm,
// different word, reads as inconsistent.
const DIMENSION_LABEL: Record<string, string> = {
  colour: 'Colour',
  color: 'Colour',
  formality: 'Formality',
  proportion: 'Fit',
  fit: 'Fit',
  texture: 'Texture',
  pattern: 'Texture',
};

export function dimensionLabel(dimension: QuickReadDimension): string {
  return DIMENSION_LABEL[dimension.toLowerCase()] ?? sentenceCase(dimension);
}

export function IconBadge({ dimension }: { dimension: QuickReadDimension }): React.ReactElement {
  const Glyph = DIMENSION_GLYPH[dimension.toLowerCase()] ?? DotGlyph;
  return (
    <View style={styles.iconBadge}>
      <Glyph />
    </View>
  );
}

export function EyeBadge(): React.ReactElement {
  return (
    <View style={styles.iconBadge}>
      <View style={styles.eyeOuter}>
        <View style={styles.eyePupil} />
      </View>
    </View>
  );
}

// --- Formality step indicator (§7.8 "formality quick read gets a step
// indicator") -----------------------------------------------------------
// The one quick-read dimension that's inherently ordinal — a ranked
// sequence of garments, not a contrast or spatial fact — so it earns a
// lightweight chart the other three (colour, texture, fit) deliberately do
// not get. Bar length comes from each garment's own `formality` (§5.4);
// the amber fade is by RANK, not by value, so the step-down reads clearly
// even when two garments sit close in formality.
const FORMALITY_BAR_MAX_HEIGHT = 28;
const FORMALITY_BAR_MIN_HEIGHT = 6;
const FORMALITY_STEP_OPACITY = [1, 0.72, 0.5, 0.32, 0.2];

export interface FormalityGarment {
  formality: number | null | undefined;
}

export function FormalityStepBars({
  garments,
}: {
  garments: FormalityGarment[];
}): React.ReactElement | null {
  const ranked = garments
    .filter((garment): garment is { formality: number } => typeof garment.formality === 'number')
    .slice()
    .sort((a, b) => b.formality - a.formality);
  if (ranked.length === 0) return null;

  return (
    <View style={styles.formalitySteps}>
      {ranked.map((garment, index) => {
        const clamped = Math.max(0, Math.min(1, garment.formality));
        const height =
          FORMALITY_BAR_MIN_HEIGHT + clamped * (FORMALITY_BAR_MAX_HEIGHT - FORMALITY_BAR_MIN_HEIGHT);
        const opacity =
          FORMALITY_STEP_OPACITY[index] ?? FORMALITY_STEP_OPACITY[FORMALITY_STEP_OPACITY.length - 1];
        return (
          <View
            key={index}
            style={[styles.formalityStepBar, { height, opacity } as ViewStyle]}
          />
        );
      })}
    </View>
  );
}

function ColourGlyph(): React.ReactElement {
  return (
    <View style={styles.colourGlyphRow}>
      <View style={[styles.colourGlyphDot, { backgroundColor: colors.text }]} />
      <View style={[styles.colourGlyphDot, styles.colourGlyphDotOverlap, { backgroundColor: colors.accent }]} />
    </View>
  );
}

function FormalityGlyph(): React.ReactElement {
  return (
    <View style={styles.formalityGlyph}>
      <View style={styles.formalityGlyphDot} />
      <View style={styles.formalityGlyphBar} />
      <View style={styles.formalityGlyphDot} />
    </View>
  );
}

function RulerGlyph(): React.ReactElement {
  return (
    <View style={styles.rulerGlyph}>
      {[0, 1, 2, 3].map((tick) => (
        <View key={tick} style={[styles.rulerTick, tick % 2 === 0 && styles.rulerTickTall]} />
      ))}
    </View>
  );
}

function TextureGlyph(): React.ReactElement {
  return (
    <View style={styles.textureGlyph}>
      {[0, 1, 2, 3].map((dot) => (
        <View key={dot} style={styles.textureDot} />
      ))}
    </View>
  );
}

function DotGlyph(): React.ReactElement {
  return <View style={styles.textureDot} />;
}

// --- Empty-state hanger glyph (§7.9 "upload card is guided, not a void") ---
export function HangerIcon(): React.ReactElement {
  return (
    <View style={styles.hanger}>
      <View style={styles.hangerHook} />
      <View style={[styles.hangerArm, styles.hangerArmLeft]} />
      <View style={[styles.hangerArm, styles.hangerArmRight]} />
      <View style={styles.hangerBar} />
    </View>
  );
}

const styles = StyleSheet.create({
  passwordField: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    marginBottom: space.sm,
    paddingRight: space.sm,
  },
  passwordInput: {
    ...type.body,
    color: colors.text,
    flex: 1,
    paddingHorizontal: space.md,
    paddingVertical: space.md,
  },
  passwordToggle: { padding: space.xs },
  pwEyeOuter: {
    width: 20,
    height: 13,
    borderRadius: 10,
    borderWidth: 1.5,
    borderColor: colors.textMuted,
    alignItems: 'center',
    justifyContent: 'center',
  },
  pwEyePupil: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.textMuted },
  pwEyeClosed: { width: 20, height: 1.5, borderRadius: 1, backgroundColor: colors.textMuted },

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
  // §2.6 AAA contrast note: Slate on Bone measures ~3.24:1, under the 4.5:1
  // floor — fine for meta/caption text, not for a button label (load-
  // bearing). The "quiet" variant keeps its lighter weight from having no
  // fill/border, not from a label that fails contrast.
  buttonLabelQuiet: { color: colors.text },

  chip: {
    paddingVertical: space.sm,
    paddingHorizontal: space.md,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    marginRight: space.sm,
    marginBottom: space.sm,
  },
  // §7.9 "occasion chips need a selected state... the user must see their
  // choice" — filled Ink with Bone text, not a light accent tint, so the
  // selected chip reads unmistakably against the five unselected outlines.
  chipSelected: { borderColor: colors.text, backgroundColor: colors.text },
  chipLabel: { ...type.meta, color: colors.textMuted },
  chipLabelSelected: { ...type.meta, color: colors.background, fontWeight: weight.medium },

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

  meter: { flex: 1 },
  meterHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: space.xs,
  },
  meterLabel: { ...type.meta, color: colors.textMuted },
  meterLevel: { ...type.meta, color: colors.text, fontWeight: weight.medium },
  meterTrack: {
    height: 8,
    borderRadius: radius.pill,
    backgroundColor: colors.border,
    overflow: 'hidden',
  },
  meterFill: {
    height: '100%',
    borderRadius: radius.pill,
    // §7.8 amber fill — hue is still constant across strong/partial/off, so
    // this doesn't trip §2.6's "never use colour to deliver the verdict."
    backgroundColor: colors.accent,
  },

  disclosureHead: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: space.md,
    borderTopWidth: 1,
    borderBottomWidth: 1,
    borderColor: colors.border,
  },
  disclosureLabel: { ...type.bodyMedium, color: colors.text },
  disclosureGlyph: { ...type.title, color: colors.textMuted },
  disclosureBody: { paddingTop: space.lg },

  swatchRow: { flexDirection: 'row', gap: space.xs, marginTop: space.sm },
  swatch: {
    width: 32,
    height: 32,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },

  // --- Icon badges ---
  iconBadge: {
    width: 32,
    height: 32,
    borderRadius: radius.pill,
    backgroundColor: '#FAF2E1',
    alignItems: 'center',
    justifyContent: 'center',
  },
  eyeOuter: {
    width: 16,
    height: 10,
    borderRadius: 8,
    borderWidth: 1.5,
    borderColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
  eyePupil: { width: 5, height: 5, borderRadius: 2.5, backgroundColor: colors.accent },
  formalitySteps: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 4,
    height: FORMALITY_BAR_MAX_HEIGHT,
    marginTop: space.xs,
  },
  formalityStepBar: { width: 8, borderRadius: 2, backgroundColor: colors.accent },
  colourGlyphRow: { flexDirection: 'row' },
  colourGlyphDot: { width: 10, height: 10, borderRadius: 5 },
  colourGlyphDotOverlap: { marginLeft: -4 },
  formalityGlyph: { flexDirection: 'row', alignItems: 'center', width: 18 },
  formalityGlyphDot: { width: 5, height: 5, borderRadius: 2.5, backgroundColor: colors.accent },
  formalityGlyphBar: { flex: 1, height: 1.5, backgroundColor: colors.accent, marginHorizontal: 2 },
  rulerGlyph: { flexDirection: 'row', alignItems: 'flex-end', gap: 2, height: 14 },
  rulerTick: { width: 1.5, height: 7, backgroundColor: colors.accent },
  rulerTickTall: { height: 14 },
  textureGlyph: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    width: 14,
    height: 14,
    justifyContent: 'space-between',
    alignContent: 'space-between',
  },
  textureDot: { width: 4, height: 4, borderRadius: 2, backgroundColor: colors.accent },

  // A hook ring plus two arms rotated around their own centres (default RN
  // transform origin) — each arm is pre-positioned so its unrotated centre
  // sits at the midpoint of apex-to-shoulder, which is what makes the
  // rotated segment land exactly on [apex, shoulder] without needing
  // `transformOrigin` (spottier RN/Fabric support) at all.
  hanger: { width: 64, height: 30 },
  hangerHook: {
    position: 'absolute',
    left: 27.5,
    top: 1,
    width: 9,
    height: 9,
    borderRadius: 4.5,
    borderWidth: 1.5,
    borderColor: colors.textMuted,
  },
  hangerArm: {
    position: 'absolute',
    width: 26,
    height: 2,
    borderRadius: 1,
    backgroundColor: colors.textMuted,
  },
  hangerArmLeft: { left: 8.2, top: 16.3, transform: [{ rotate: '-34deg' }] },
  hangerArmRight: { left: 29.8, top: 16.3, transform: [{ rotate: '34deg' }] },
  hangerBar: {
    position: 'absolute',
    left: 10.5,
    top: 23.8,
    width: 43,
    height: 1.5,
    borderRadius: 0.75,
    backgroundColor: colors.textMuted,
  },
});
