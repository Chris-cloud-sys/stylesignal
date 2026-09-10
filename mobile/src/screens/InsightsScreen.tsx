/**
 * Personal signal history — SPEC+ (docs/spec-deviations.md).
 *
 * The wardrobe-free answer to "what should I wear from what I own": pattern
 * insight aggregated from signals the pipeline already computes on every
 * scan (palette, formality, the two §7.7 meters), not a new catalogue of
 * what the caller owns. Same descriptive-language spirit as the rest of
 * the app — rates are phrased in words, never shown as raw percentages.
 */
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { fetchInsights } from '../api/client';
import type { Insights } from '../api/types';
import { SectionLabel } from '../components/primitives';
import { colors, radius, sentenceCase, space, type } from '../theme';

interface Props {
  onBack: () => void;
}

function rateLabel(rate: number | null | undefined): string | null {
  if (rate == null) return null;
  if (rate >= 0.75) return 'most';
  if (rate >= 0.5) return 'more than half';
  if (rate >= 0.25) return 'some';
  return 'a few';
}

export function InsightsScreen({ onBack }: Props): React.ReactElement {
  const [insights, setInsights] = useState<Insights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchInsights()
      .then((result) => {
        if (!cancelled) setInsights(result);
      })
      .catch(() => {
        if (!cancelled) setError('Could not load your insights.');
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
        <Pressable onPress={onBack} accessibilityRole="button">
          <Text style={styles.backLink}>Back</Text>
        </Pressable>
        <Text style={styles.title}>Your style, so far</Text>
      </View>

      {loading ? (
        <ActivityIndicator color={colors.textMuted} style={styles.spinner} />
      ) : error ? (
        <Text style={styles.error}>{error}</Text>
      ) : insights && !insights.ready ? (
        <View style={styles.body}>
          <Text style={styles.notReady}>
            Scan {insights.minimum_scans - insights.scan_count} more{' '}
            {insights.minimum_scans - insights.scan_count === 1 ? 'outfit' : 'outfits'} to
            unlock pattern insights from your reads so far ({insights.scan_count} of{' '}
            {insights.minimum_scans}).
          </Text>
        </View>
      ) : insights ? (
        <View style={styles.body}>
          <Text style={styles.intro}>
            Pulled from your last {insights.scan_count} reads — no wardrobe to set up,
            just what StyleSignal already noticed.
          </Text>

          {insights.average_formality_label ? (
            <View style={styles.block}>
              <SectionLabel>Typical register</SectionLabel>
              <Text style={styles.value}>{sentenceCase(insights.average_formality_label)}</Text>
            </View>
          ) : null}

          {insights.top_colours.length > 0 ? (
            <View style={styles.block}>
              <SectionLabel>Colours that come up most</SectionLabel>
              <View style={styles.colourRow}>
                {insights.top_colours.map((colour) => (
                  <View key={colour.hex} style={styles.colourItem}>
                    <View style={[styles.swatch, { backgroundColor: colour.hex }]} />
                    <Text style={styles.colourCount}>{colour.scan_count}</Text>
                  </View>
                ))}
              </View>
            </View>
          ) : null}

          {insights.most_common_occasion ? (
            <View style={styles.block}>
              <SectionLabel>Most-tagged occasion</SectionLabel>
              <Text style={styles.value}>{sentenceCase(insights.most_common_occasion)}</Text>
            </View>
          ) : null}

          {rateLabel(insights.occasion_match_strong_rate) ? (
            <View style={styles.block}>
              <SectionLabel>Occasion match</SectionLabel>
              <Text style={styles.value}>
                {sentenceCase(rateLabel(insights.occasion_match_strong_rate) ?? '')} of your
                reads land as a strong match for their occasion.
              </Text>
            </View>
          ) : null}

          {rateLabel(insights.signal_clarity_strong_rate) ? (
            <View style={styles.block}>
              <SectionLabel>Signal clarity</SectionLabel>
              <Text style={styles.value}>
                {sentenceCase(rateLabel(insights.signal_clarity_strong_rate) ?? '')} of your
                reads come through with a clear signal.
              </Text>
            </View>
          ) : null}

          <View style={styles.block}>
            <SectionLabel>How you capture</SectionLabel>
            <Text style={styles.value}>
              {insights.worn_count} worn on you, {insights.item_count} read as an item.
            </Text>
          </View>
        </View>
      ) : null}
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
  backLink: { ...type.body, color: colors.accent, fontWeight: '600', marginBottom: space.sm },
  title: { ...type.title, color: colors.text },
  spinner: { marginTop: space.xl },
  body: { paddingHorizontal: space.lg, paddingBottom: space.xxl },
  intro: { ...type.body, color: colors.textMuted, marginBottom: space.lg },
  notReady: { ...type.body, color: colors.textMuted },
  block: { marginBottom: space.lg },
  value: { ...type.bodyMedium, color: colors.text, marginTop: space.xs },
  colourRow: { flexDirection: 'row', gap: space.md, marginTop: space.xs },
  colourItem: { alignItems: 'center', gap: 4 },
  swatch: {
    width: 32,
    height: 32,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  colourCount: { ...type.meta, color: colors.textMuted },
  error: {
    ...type.meta,
    color: colors.systemError,
    paddingHorizontal: space.lg,
    marginTop: space.sm,
  },
});
