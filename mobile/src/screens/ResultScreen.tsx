/**
 * The read — spec §4.1, §6.2, §7.
 *
 * Three states: pending (skeleton), complete (result), failed (typed reason +
 * retry). Nothing on this screen colour-codes a verdict — §2.6 forbids it, and
 * the feedback is language, not a grade.
 */
import { Ionicons } from '@expo/vector-icons';
import { File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';
import React, { useRef, useState } from 'react';
import { Image, Pressable, ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { captureRef } from 'react-native-view-shot';

import { absoluteMediaUrl, addToWardrobe, ApiError, rereadOutfit } from '../api/client';
import type {
  FailureReason,
  Feedback,
  Garment,
  Meter as MeterData,
  OutfitDetail,
  QuickRead,
} from '../api/types';
import { useOutfitPolling } from '../api/useOutfitPolling';
import {
  Button,
  Chip,
  Disclosure,
  Divider,
  dimensionLabel,
  EyeBadge,
  FormalityStepBars,
  IconBadge,
  Meter,
  SectionLabel,
  SkeletonLine,
  Swatches,
} from '../components/primitives';
import { ShareCard } from '../components/ShareCard';
import { OCCASIONS, type Occasion } from '../config';
import { colors, radius, sentenceCase, space, type, weight } from '../theme';

/** §7.7 meter labels — plain English, not the wire-format field name. */
const METER_LABELS: Record<'occasion_match' | 'signal_clarity', string> = {
  occasion_match: 'Occasion match',
  signal_clarity: 'Signal clarity',
};

interface Props {
  outfitId: string;
  onDone: () => void;
  /** Result-screen "change occasion & re-read" — hands the new outfit's id
   * back up so the caller can navigate to its own result screen. */
  onReread: (outfitId: string) => void;
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

export function ResultScreen({ outfitId, onDone, onReread }: Props): React.ReactElement {
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

  return <Complete outfit={outfit} onDone={onDone} onReread={onReread} />;
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
        <View style={styles.hero}>
          <Image source={{ uri: thumb }} style={styles.heroImage} resizeMode="contain" />
        </View>
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
  onReread,
}: {
  outfit: OutfitDetail;
  onDone: () => void;
  onReread: (outfitId: string) => void;
}): React.ReactElement {
  const feedback = outfit.feedback;
  const thumb = absoluteMediaUrl(outfit.thumb_url);
  const shareCardRef = useRef<View>(null);
  const [sharing, setSharing] = useState(false);
  const [inWardrobe, setInWardrobe] = useState(outfit.in_wardrobe ?? false);
  const [addingToWardrobe, setAddingToWardrobe] = useState(false);

  const handleShare = async (): Promise<void> => {
    if (!feedback || sharing) return;
    setSharing(true);
    try {
      await shareFeedbackImage(shareCardRef, feedback);
    } finally {
      setSharing(false);
    }
  };

  // SPEC+ — wardrobe catalog (docs/spec-deviations.md). Only offered for an
  // item-mode read; a worn-outfit photo has no single garment to snapshot.
  const handleAddToWardrobe = async (): Promise<void> => {
    if (inWardrobe || addingToWardrobe) return;
    setAddingToWardrobe(true);
    try {
      await addToWardrobe(outfit.outfit_id);
      setInWardrobe(true);
    } catch {
      // Leave the button as-is — the user can retry.
    } finally {
      setAddingToWardrobe(false);
    }
  };

  return (
    <ScrollView contentContainerStyle={styles.container}>
      {/* A second way back besides the bottom "Scan another outfit" CTA —
          not everyone wants to scroll the whole read to leave. */}
      <View style={styles.topBar}>
        <Pressable onPress={onDone} accessibilityRole="button">
          <Text style={styles.topBarLink}>Home</Text>
        </Pressable>
        {/* Owner-visible like count (§ SPEC+ likes) — present only when the
            outfit is shared with the community; see get_outfit in
            outfits.py, which only populates this for the outfit's owner. */}
        {typeof outfit.like_count === 'number' ? (
          <Text style={styles.topBarLikes}>
            ♥ {outfit.like_count} {outfit.like_count === 1 ? 'like' : 'likes'}
          </Text>
        ) : null}
      </View>

      {thumb ? (
        <View style={styles.hero}>
          <Image source={{ uri: thumb }} style={styles.heroImage} resizeMode="contain" />
          {feedback ? (
            // §7.8 "one verdict only" lives ON the photo — the read is the
            // headline, not a caption underneath it.
            <View style={styles.heroScrim}>
              {outfit.occasion || outfit.capture_mode === 'item' ? (
                <Text style={styles.heroOccasion}>
                  {outfit.occasion ? `Read for ${sentenceCase(outfit.occasion)}` : 'Item read'}
                  {outfit.capture_mode === 'item' ? ' · Not worn' : ''}
                </Text>
              ) : null}
              <Text style={styles.heroVerdictPhrase}>{feedback.verdict_phrase}</Text>
              {feedback.verdict_subtitle ? (
                <Text style={styles.heroVerdictSubtitle}>{feedback.verdict_subtitle}</Text>
              ) : null}
            </View>
          ) : null}
        </View>
      ) : null}

      {outfit.capture_mode === 'item' && typeof outfit.in_wardrobe === 'boolean' ? (
        <Button
          variant={inWardrobe ? 'secondary' : 'primary'}
          label={inWardrobe ? 'Added to wardrobe' : 'Add to wardrobe'}
          onPress={() => void handleAddToWardrobe()}
          disabled={inWardrobe}
          busy={addingToWardrobe}
          style={styles.wardrobeButton}
        />
      ) : null}

      {feedback ? <Headline feedback={feedback} /> : null}
      {feedback && feedback.quick_reads.length > 0 ? (
        <QuickReads items={feedback.quick_reads} garments={outfit.garments ?? []} />
      ) : null}
      {feedback && feedback.elevate_suggestion ? (
        <ElevateSuggestion text={feedback.elevate_suggestion} />
      ) : null}

      {feedback ? (
        <>
          <Divider />
          <Disclosure label="See full read">
            <FullRead feedback={feedback} garments={outfit.garments ?? []} />
          </Disclosure>
        </>
      ) : null}

      {feedback ? (
        <Button
          variant="secondary"
          label="Share this read"
          onPress={handleShare}
          busy={sharing}
          style={styles.shareButton}
        />
      ) : null}

      {feedback ? (
        <>
          <Divider />
          <ChangeOccasion
            outfitId={outfit.outfit_id}
            currentOccasion={outfit.occasion ?? null}
            onRead={onReread}
          />
        </>
      ) : null}

      <Divider />
      <Text style={styles.footnote}>
        This describes how the outfit reads. What you do with it is yours.
      </Text>

      <Button label="Scan another outfit" onPress={onDone} style={styles.cta} />

      {/* Off-screen — mounted so it's ready to capture, never shown to the user. */}
      {feedback ? (
        <View style={styles.offscreen} pointerEvents="none">
          <ShareCard
            ref={shareCardRef}
            photoUri={thumb}
            occasion={outfit.occasion}
            feedback={feedback}
          />
        </View>
      ) : null}
    </ScrollView>
  );
}

// --- Change occasion & re-read -----------------------------------------------
// A real scan against the same photo, not a free cache hit — the backend's
// image-hash cache is keyed on (image, occasion) specifically so an
// occasion change never reuses another occasion's notes. See
// reread_outfit's docstring in outfits.py.
function ChangeOccasion({
  outfitId,
  currentOccasion,
  onRead,
}: {
  outfitId: string;
  currentOccasion: string | null;
  onRead: (outfitId: string) => void;
}): React.ReactElement {
  const [selected, setSelected] = useState<Occasion | null>(currentOccasion as Occasion | null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const changed = selected !== currentOccasion;

  const submit = async (): Promise<void> => {
    if (!changed || busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await rereadOutfit(outfitId, selected);
      onRead(created.outfit_id);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : 'Could not reach StyleSignal. Check your connection.',
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.rereadBlock}>
      <SectionLabel>Different occasion?</SectionLabel>
      <Text style={styles.rereadHint}>
        Change the tag for a fresh read of this same photo — uses another scan.
      </Text>
      <View style={styles.chipWrap}>
        {OCCASIONS.map((value) => (
          <Chip
            key={value}
            label={sentenceCase(value)}
            selected={selected === value}
            onPress={() => setSelected(value)}
          />
        ))}
      </View>
      {error ? <Text style={styles.rereadError}>{error}</Text> : null}
      <Button
        variant="secondary"
        label="Re-read with this occasion"
        onPress={() => void submit()}
        disabled={!changed}
        busy={busy}
        style={styles.rereadButton}
      />
    </View>
  );
}

// --- Share ("Share this read") ----------------------------------------------
// Captures the off-screen ShareCard (see components/ShareCard.tsx) to a PNG
// and hands it to the native share sheet. Needs a dev client build —
// react-native-view-shot isn't in Expo Go's managed SDK (see
// docs/spec-deviations.md #14). Falls back to a text-only share if the
// image capture or the share sheet itself is unavailable, so this degrades
// gracefully rather than dead-ending.
function buildShareText(feedback: Feedback): string {
  const lines = [feedback.verdict_phrase];
  if (feedback.verdict_subtitle) lines.push(feedback.verdict_subtitle);
  if (feedback.quick_reads.length > 0) {
    lines.push('');
    for (const item of feedback.quick_reads) {
      lines.push(`${sentenceCase(item.dimension)}: ${item.text}`);
    }
  }
  lines.push('');
  // "Try it now" phase 1 — same brand-only line as ShareCard's watermark,
  // no domain/store link until phase 2 has one to point at.
  lines.push('Get your own read — StyleSignal');
  return lines.join('\n');
}

function shareFeedbackText(feedback: Feedback): void {
  Share.share({ message: buildShareText(feedback) }).catch(() => {
    // User cancelled or the share sheet failed to open — nothing to recover.
  });
}

async function shareFeedbackImage(
  cardRef: React.RefObject<View | null>,
  feedback: Feedback,
): Promise<void> {
  try {
    const canShareFile = await Sharing.isAvailableAsync();
    if (!canShareFile || !cardRef.current) {
      shareFeedbackText(feedback);
      return;
    }
    // react-native-view-shot's own tmp directory isn't one expo-sharing's
    // FileProvider config covers on Android — sharing straight from there
    // throws a native FileProvider exception that crashes the app instead
    // of rejecting the promise, so this try/catch never even sees it.
    // Copying into expo-file-system's cache dir first keeps the file
    // somewhere Sharing.shareAsync is actually configured to hand off.
    const capturedUri = await captureRef(cardRef, { format: 'png', quality: 1 });
    const shareableFile = new File(Paths.cache, `stylesignal-share-${Date.now()}.png`);
    new File(capturedUri).copy(shareableFile);
    await Sharing.shareAsync(shareableFile.uri, {
      mimeType: 'image/png',
      dialogTitle: 'Share this read',
    });
  } catch {
    // Capture or the share sheet failed (or the user cancelled) — text still
    // gets the read across.
    shareFeedbackText(feedback);
  }
}

// --- Zone 1: headline (§7.7) -------------------------------------------------
function Headline({ feedback }: { feedback: Feedback }): React.ReactElement {
  const meters: Array<['occasion_match' | 'signal_clarity', MeterData | null | undefined]> = [
    ['occasion_match', feedback.occasion_match],
    ['signal_clarity', feedback.signal_clarity],
  ];
  const activeMeters = meters.filter(([, meter]) => meter != null) as Array<
    ['occasion_match' | 'signal_clarity', MeterData]
  >;

  return (
    <View style={styles.headline}>
      {activeMeters.length > 0 ? (
        <View style={styles.meterRow}>
          {activeMeters.map(([key, meter]) => (
            <Meter key={key} label={METER_LABELS[key]} level={meter.level} score={meter.score} />
          ))}
        </View>
      ) : null}

      {feedback.palette.length > 0 ? (
        <View style={styles.paletteBlock}>
          <SectionLabel>Garment palette</SectionLabel>
          <Swatches hexes={feedback.palette.map((colour) => colour.hex)} />
        </View>
      ) : null}

      {feedback.focal_point ? (
        <View style={styles.focalPointBox}>
          <EyeBadge />
          <Text style={styles.focalPointText}>
            <Text style={styles.focalPointLabel}>Eye lands at: </Text>
            {feedback.focal_point}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

// --- Elevate suggestion (SPEC+) ----------------------------------------------
// The one deliberate, bounded exception to "descriptive, not prescriptive"
// (docs/spec-deviations.md) — kept visually separate from the core read
// (its own box, its own label) rather than folded into Zone 1/2, so the
// no-prescription promise still reads as true for everything above it.
function ElevateSuggestion({ text }: { text: string }): React.ReactElement {
  return (
    <View style={styles.elevateBox}>
      <View style={styles.elevateIcon}>
        <Ionicons name="sparkles-outline" size={16} color={colors.accent} />
      </View>
      <View style={styles.elevateCopy}>
        <Text style={styles.elevateLabel}>One idea, if you want it</Text>
        <Text style={styles.elevateText}>{text}</Text>
      </View>
    </View>
  );
}

// --- Zone 2: quick reads (§7.7) ----------------------------------------------
function QuickReads({
  items,
  garments,
}: {
  items: QuickRead[];
  garments: Garment[];
}): React.ReactElement {
  return (
    <View style={styles.quickReads}>
      {items.map((item, index) => (
        <View key={`${item.dimension}-${index}`} style={styles.quickReadItem}>
          <IconBadge dimension={item.dimension} />
          <View style={styles.quickReadBody}>
            <SectionLabel>{dimensionLabel(item.dimension)}</SectionLabel>
            <Text style={styles.quickRead}>{item.text}</Text>
            {/* §7.8 "formality quick read gets a step indicator" — the
                only ordinal one of the four, so it's the only one that
                earns a chart; colour/texture/fit stay icon + text. */}
            {item.dimension.toLowerCase() === 'formality' ? (
              <FormalityStepBars garments={garments} />
            ) : null}
          </View>
        </View>
      ))}
    </View>
  );
}

// --- Zone 3: full read (pre-§7.7 screen, now collapsed) ----------------------
function FullRead({
  feedback,
  garments,
}: {
  feedback: Feedback;
  garments: Garment[];
}): React.ReactElement {
  const fullRead = feedback.full_read;
  const noteFor = (garmentId: string): string | undefined =>
    fullRead.garment_notes.find((note) => note.garment_id === garmentId)?.note;

  return (
    <>
      <Text style={styles.overall}>{fullRead.overall_read}</Text>

      <Divider />

      <Section label="Colour" body={fullRead.color_note} />
      <Section label="Formality" body={fullRead.formality_note} />
      {fullRead.proportion_note ? (
        <Section label="Proportion and line" body={fullRead.proportion_note} />
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
  topBar: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    marginBottom: space.sm,
  },
  topBarLink: { ...type.meta, color: colors.textMuted },
  topBarLikes: { ...type.meta, color: colors.accent },
  stage: { ...type.meta, color: colors.textMuted, marginBottom: space.md },
  wardrobeButton: { marginBottom: space.lg },
  // §7.8 the hero is a container for the photo AND the scrim-mounted
  // verdict, not the `<Image>` itself — that's what makes the overlay
  // possible.
  hero: {
    width: '100%',
    aspectRatio: 3 / 4,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    marginBottom: space.lg,
    overflow: 'hidden',
  },
  // `contain`, never `cover` — §7.8 "never crop the head." A photo whose
  // aspect ratio doesn't match the frame letterboxes onto `colors.surface`
  // instead of losing the top of the frame.
  heroImage: { width: '100%', height: '100%' },
  heroPlaceholder: { borderWidth: 1, borderColor: colors.border },
  // Pinned to the bottom of the photo, not the screen — §7.8 "one verdict
  // only" reads as part of the photograph, the way the mockup has it.
  heroScrim: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(26,26,26,0.72)',
    paddingHorizontal: space.lg,
    paddingTop: space.lg,
    paddingBottom: space.lg,
  },
  heroOccasion: { ...type.meta, color: colors.background, marginBottom: space.xs },
  // Deliberately bigger than the shared `type.display` token (used elsewhere
  // for the sign-in wordmark) — this is a targeted push for the verdict's
  // visual weight, not a change to the type scale generally.
  heroVerdictPhrase: {
    fontSize: 34,
    lineHeight: 40,
    fontWeight: weight.regular,
    letterSpacing: -0.3,
    color: colors.background,
  },
  heroVerdictSubtitle: {
    ...type.body,
    fontSize: 17,
    lineHeight: 24,
    color: colors.background,
    opacity: 0.85,
    marginTop: space.xs,
  },
  pendingHint: { ...type.body, color: colors.textMuted, marginBottom: space.xl },
  skeletonBlock: { marginBottom: space.xl },

  overall: { ...type.body, color: colors.text, fontSize: 18, lineHeight: 28 },

  // --- §7.7 Zone 1: headline ---
  headline: { marginBottom: space.lg },
  meterRow: { flexDirection: 'row', gap: space.lg, marginBottom: space.md },
  paletteBlock: { marginBottom: space.md },
  // A contained tag, not a full-width paragraph — matches the design
  // canvas's pill treatment, but as a box that wraps rather than a rigid
  // single-line pill, since focal_point can run up to twelve words.
  focalPointBox: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    alignSelf: 'flex-start',
    maxWidth: '100%',
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    paddingVertical: space.sm,
    marginTop: space.sm,
  },
  focalPointLabel: { ...type.meta, color: colors.textMuted },
  focalPointText: { ...type.meta, color: colors.text, fontWeight: weight.medium, flexShrink: 1 },

  // Deliberately set apart from Headline/QuickReads (its own bordered box,
  // amber-tinted, not plain surface) — this is the one field that carries a
  // suggestion, and it should read as visually optional/secondary, not as
  // part of the core descriptive read above it.
  elevateBox: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: space.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: '#FAF2E1',
    borderRadius: radius.md,
    paddingHorizontal: space.md,
    paddingVertical: space.sm,
    marginTop: space.md,
  },
  elevateIcon: { marginTop: 2 },
  elevateCopy: { flex: 1 },
  elevateLabel: { ...type.meta, color: colors.textMuted, marginBottom: 2 },
  elevateText: { ...type.meta, color: colors.text, fontWeight: weight.medium },

  // --- §7.7 Zone 2: quick reads ---
  quickReads: { gap: space.lg, marginBottom: space.lg },
  quickReadItem: { flexDirection: 'row', gap: space.sm },
  quickReadBody: { flex: 1, gap: space.xs },
  quickRead: { ...type.body, fontSize: 17, lineHeight: 25, color: colors.text },

  shareButton: { marginBottom: space.md },
  offscreen: { position: 'absolute', top: 0, left: -2000 },

  rereadBlock: { marginVertical: space.lg },
  rereadHint: { ...type.meta, color: colors.textMuted, marginBottom: space.sm },
  rereadError: { ...type.meta, color: colors.systemError, marginBottom: space.sm },
  rereadButton: { marginTop: space.sm },
  chipWrap: { flexDirection: 'row', flexWrap: 'wrap' },

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
