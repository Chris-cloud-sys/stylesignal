/**
 * The read — spec §4.1, §6.2, §7.
 *
 * Three states: pending (skeleton), complete (result), failed (typed reason +
 * retry). Nothing on this screen colour-codes a verdict — §2.6 forbids it, and
 * the feedback is language, not a grade.
 */
import React from 'react';
import { Image, ScrollView, StyleSheet, Text, View } from 'react-native';

import { absoluteMediaUrl } from '../api/client';
import type { FailureReason, Garment, OutfitDetail } from '../api/types';
import { useOutfitPolling } from '../api/useOutfitPolling';
import {
  Button,
  Divider,
  SectionLabel,
  SkeletonLine,
  Swatches,
} from '../components/primitives';
import { colors, radius, sentenceCase, space, type } from '../theme';

interface Props {
  outfitId: string;
  onDone: () => void;
}

/** §5.3 failure reasons, said plainly. Never blame the user. */
const FAILURE_COPY: Record<FailureReason, { title: string; body: string }> = {
  undecodable: {
    title: 'That file could not be opened',
    body: 'The image did not decode. A JPEG or PNG straight from the camera roll usually works.',
  },
  no_person: {
    title: 'No one in frame',
    body: 'StyleSignal reads outfits as worn, so it needs a photo with the look on a person.',
  },
  no_garments_detected: {
    title: 'No garments found',
    body: 'Nothing in the frame read as clothing. A fuller, better-lit shot of the whole look gives it more to go on.',
  },
  internal_error: {
    title: 'Something went wrong on our end',
    body: 'The scan did not finish. This one is on us — trying again usually clears it.',
  },
};

export function ResultScreen({ outfitId, onDone }: Props): React.ReactElement {
  const { state, retry } = useOutfitPolling(outfitId);

  if (state.phase === 'error') {
    return (
      <Centered
        title="Could not load this read"
        body={state.message}
        primaryLabel="Try again"
        onPrimary={retry}
        onDone={onDone}
      />
    );
  }

  if (state.phase === 'loading') {
    return <Pending outfit={state.outfit} onDone={onDone} />;
  }

  const outfit = state.outfit;

  if (outfit.status === 'failed') {
    const copy = FAILURE_COPY[outfit.failure_reason ?? 'internal_error'];
    return (
      <Centered
        title={copy.title}
        body={copy.body}
        primaryLabel="Scan another outfit"
        onPrimary={onDone}
        onDone={onDone}
      />
    );
  }

  return <Complete outfit={outfit} onDone={onDone} />;
}

// --- Pending (§4.1 skeleton) ----------------------------------------------
function Pending({
  outfit,
  onDone,
}: {
  outfit?: OutfitDetail;
  onDone: () => void;
}): React.ReactElement {
  const thumb = absoluteMediaUrl(outfit?.thumb_url);
  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.stage}>Reading the look</Text>
      {thumb ? (
        <Image source={{ uri: thumb }} style={styles.hero} resizeMode="cover" />
      ) : (
        <View style={[styles.hero, styles.heroPlaceholder]} />
      )}

      <Text style={styles.pendingHint}>
        Working through the colours, the register and the line. This usually
        takes a few seconds.
      </Text>

      <View style={styles.skeletonBlock}>
        <SkeletonLine width="40%" />
        <SkeletonLine />
        <SkeletonLine />
        <SkeletonLine width="72%" />
      </View>
      <View style={styles.skeletonBlock}>
        <SkeletonLine width="30%" />
        <SkeletonLine />
        <SkeletonLine width="85%" />
      </View>

      <Button variant="quiet" label="Back" onPress={onDone} />
    </ScrollView>
  );
}

// --- Complete --------------------------------------------------------------
function Complete({
  outfit,
  onDone,
}: {
  outfit: OutfitDetail;
  onDone: () => void;
}): React.ReactElement {
  const feedback = outfit.feedback;
  const thumb = absoluteMediaUrl(outfit.thumb_url);
  const garments = outfit.garments ?? [];

  const noteFor = (garmentId: string): string | undefined =>
    feedback?.garment_notes.find((note) => note.garment_id === garmentId)?.note;

  return (
    <ScrollView contentContainerStyle={styles.container}>
      {thumb ? (
        <Image source={{ uri: thumb }} style={styles.hero} resizeMode="cover" />
      ) : null}

      {outfit.occasion ? (
        <Text style={styles.occasion}>
          Read for {sentenceCase(outfit.occasion)}
        </Text>
      ) : null}

      {feedback ? (
        <>
          <Text style={styles.overall}>{feedback.overall_read}</Text>

          <Divider />

          <Section label="Colour" body={feedback.color_note} />
          <Section label="Formality" body={feedback.formality_note} />
          {feedback.proportion_note ? (
            <Section label="Proportion and line" body={feedback.proportion_note} />
          ) : null}

          {garments.length > 0 ? (
            <>
              <Divider />
              <SectionLabel>Piece by piece</SectionLabel>
              {garments.map((garment) => (
                <GarmentRow
                  key={garment.garment_id}
                  garment={garment}
                  note={noteFor(garment.garment_id)}
                />
              ))}
            </>
          ) : null}
        </>
      ) : null}

      <Divider />
      <Text style={styles.footnote}>
        This describes how the outfit reads. What you do with it is yours.
      </Text>

      <Button label="Scan another outfit" onPress={onDone} style={styles.cta} />
    </ScrollView>
  );
}

function Section({ label, body }: { label: string; body: string }): React.ReactElement {
  return (
    <View style={styles.section}>
      <SectionLabel>{label}</SectionLabel>
      <Text style={styles.sectionBody}>{body}</Text>
    </View>
  );
}

function GarmentRow({
  garment,
  note,
}: {
  garment: Garment;
  note?: string;
}): React.ReactElement {
  return (
    <View style={styles.garment}>
      <View style={styles.garmentHead}>
        <Text style={styles.garmentCategory}>{sentenceCase(garment.category)}</Text>
        {garment.pattern !== 'solid' ? (
          <Text style={styles.garmentMeta}>{garment.pattern}</Text>
        ) : null}
      </View>
      <Swatches hexes={garment.colors.map((colour) => colour.hex)} />
      {note ? <Text style={styles.garmentNote}>{note}</Text> : null}
    </View>
  );
}

// --- Shared state screen ---------------------------------------------------
function Centered({
  title,
  body,
  primaryLabel,
  onPrimary,
  onDone,
}: {
  title: string;
  body: string;
  primaryLabel: string;
  onPrimary: () => void;
  onDone: () => void;
}): React.ReactElement {
  return (
    <View style={styles.centered}>
      <Text style={styles.centeredTitle}>{title}</Text>
      <Text style={styles.centeredBody}>{body}</Text>
      <Button label={primaryLabel} onPress={onPrimary} style={styles.cta} />
      <Button variant="quiet" label="Back" onPress={onDone} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { padding: space.lg, paddingBottom: space.xxl },
  stage: { ...type.meta, color: colors.textMuted, marginBottom: space.md },
  hero: {
    width: '100%',
    aspectRatio: 3 / 4,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    marginBottom: space.lg,
  },
  heroPlaceholder: { borderWidth: 1, borderColor: colors.border },
  pendingHint: { ...type.body, color: colors.textMuted, marginBottom: space.xl },
  skeletonBlock: { marginBottom: space.xl },

  occasion: { ...type.meta, color: colors.textMuted, marginBottom: space.sm },
  overall: { ...type.body, color: colors.text, fontSize: 18, lineHeight: 28 },

  section: { marginBottom: space.lg },
  sectionBody: { ...type.body, color: colors.text },

  garment: {
    paddingVertical: space.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  garmentHead: { flexDirection: 'row', alignItems: 'baseline' },
  garmentCategory: { ...type.bodyMedium, color: colors.text },
  garmentMeta: { ...type.meta, color: colors.textMuted, marginLeft: space.sm },
  garmentNote: { ...type.body, color: colors.text, marginTop: space.sm },

  footnote: { ...type.meta, color: colors.textMuted },
  cta: { marginTop: space.lg, marginBottom: space.sm },

  centered: {
    flex: 1,
    justifyContent: 'center',
    padding: space.lg,
    backgroundColor: colors.background,
  },
  centeredTitle: { ...type.title, color: colors.text, marginBottom: space.sm },
  centeredBody: { ...type.body, color: colors.textMuted },
});
