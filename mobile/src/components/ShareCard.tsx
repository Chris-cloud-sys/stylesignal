/**
 * The exportable share card — the design canvas's "ShareCard" direction,
 * rendered off-screen and captured to a PNG for the native share sheet.
 *
 * This is the one surface allowed more visual weight than the daily-use
 * result screen (§2.6's restraint is about the app's own chrome; this gets
 * posted once, not lived in). Two rules still hold here exactly as
 * everywhere else: no numeric score rendered as text, and no colour used to
 * carry the verdict — the meter badges are plain Ink-on-scrim regardless of
 * level, same as the in-app Meter primitive.
 */
import React from 'react';
import { Image, StyleSheet, Text, View } from 'react-native';

import type { Feedback } from '../api/types';
import { sentenceCase } from '../theme';

const CARD_WIDTH = 360;
const CARD_HEIGHT = 450;

const METER_LABELS: Record<'occasion_match' | 'signal_clarity', string> = {
  occasion_match: 'Occasion match',
  signal_clarity: 'Signal clarity',
};

const METER_LEVEL_LABEL: Record<'strong' | 'partial' | 'off', string> = {
  strong: 'Strong',
  partial: 'Partial',
  off: 'Off',
};

interface Props {
  photoUri?: string;
  occasion?: string | null;
  feedback: Feedback;
}

export const ShareCard = React.forwardRef<View, Props>(function ShareCard(
  { photoUri, occasion, feedback },
  ref,
): React.ReactElement {
  const meters: Array<['occasion_match' | 'signal_clarity', 'strong' | 'partial' | 'off']> = [];
  if (feedback.occasion_match) meters.push(['occasion_match', feedback.occasion_match.level]);
  if (feedback.signal_clarity) meters.push(['signal_clarity', feedback.signal_clarity.level]);

  const subtitle = feedback.verdict_subtitle ?? feedback.quick_reads[0]?.text;

  return (
    <View ref={ref} collapsable={false} style={styles.card}>
      {photoUri ? (
        <Image source={{ uri: photoUri }} style={styles.photo} resizeMode="cover" />
      ) : (
        <View style={[styles.photo, styles.photoPlaceholder]} />
      )}

      <View style={styles.wordmarkRow}>
        <View style={styles.wordmarkDot} />
        <Text style={styles.wordmark}>StyleSignal</Text>
      </View>

      <View style={styles.scrim}>
        {occasion ? <Text style={styles.occasion}>Read for {sentenceCase(occasion)}</Text> : null}
        <Text style={styles.verdict}>{feedback.verdict_phrase}</Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}

        {feedback.palette.length > 0 ? (
          <View style={styles.swatchRow}>
            {feedback.palette.slice(0, 5).map((colour, index) => (
              <View key={`${colour.hex}-${index}`} style={[styles.swatch, { backgroundColor: colour.hex }]} />
            ))}
          </View>
        ) : null}

        {meters.length > 0 ? (
          <View style={styles.meterRow}>
            {meters.map(([key, level]) => (
              <View key={key} style={styles.meterBadge}>
                <Text style={styles.meterBadgeLabel}>{METER_LABELS[key]}</Text>
                <Text style={styles.meterBadgeLevel}>{METER_LEVEL_LABEL[level]}</Text>
              </View>
            ))}
          </View>
        ) : null}

        {/* "Try it now" phase 1 (docs/spec-deviations.md) — a static brand
            call-to-action baked into the image itself, since WhatsApp/
            iMessage/email don't reliably preserve caption text alongside a
            shared photo. No domain/store link yet, so this stays brand-only
            rather than printing a URL that doesn't resolve to anything;
            upgrade to a real link or QR code once phase 2 has one to point
            at. */}
        <Text style={styles.cta}>Get your own read — StyleSignal</Text>
      </View>
    </View>
  );
});

const styles = StyleSheet.create({
  card: {
    width: CARD_WIDTH,
    height: CARD_HEIGHT,
    borderRadius: 20,
    overflow: 'hidden',
    backgroundColor: '#1A1A1A',
  },
  photo: { ...StyleSheet.absoluteFillObject, width: undefined, height: undefined },
  photoPlaceholder: { backgroundColor: '#3A362E' },

  wordmarkRow: {
    position: 'absolute',
    top: 20,
    left: 20,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  wordmarkDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#E0A32E' },
  wordmark: { fontSize: 13, fontWeight: '500', color: '#F4F0E9', letterSpacing: 0.3 },

  scrim: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(20,18,14,0.88)',
    padding: 20,
  },
  occasion: { fontSize: 11, color: '#C9C2B4', marginBottom: 6 },
  verdict: { fontSize: 26, lineHeight: 31, fontWeight: '400', color: '#F4F0E9', letterSpacing: -0.3 },
  subtitle: { fontSize: 13, lineHeight: 19, color: '#D8D2C4', marginTop: 6, marginBottom: 14 },

  swatchRow: { flexDirection: 'row', gap: 6, marginBottom: 12 },
  swatch: {
    width: 22,
    height: 22,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: 'rgba(244,240,233,0.25)',
  },

  meterRow: { flexDirection: 'row', gap: 8, flexWrap: 'wrap' },
  meterBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: 'rgba(244,240,233,0.3)',
  },
  meterBadgeLabel: { fontSize: 11, color: '#C9C2B4' },
  meterBadgeLevel: { fontSize: 11, fontWeight: '500', color: '#F4F0E9' },

  // §2.6: amber is the accent — the one line on this card meant to prompt
  // action gets it, same rule as the in-app primary CTA.
  cta: {
    fontSize: 12,
    fontWeight: '500',
    color: '#E0A32E',
    letterSpacing: 0.2,
    marginTop: 14,
  },
});
