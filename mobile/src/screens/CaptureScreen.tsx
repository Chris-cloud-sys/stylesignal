/**
 * Capture and upload — spec §4.1.
 *
 * Camera or gallery, client-side downscale to 1600px on the long edge before
 * upload, optional occasion tag and freeform note, then hand off to the
 * result screen which polls (§6.6).
 *
 * There is no wardrobe to catalogue here on purpose (§2.3): the single-photo
 * flow owns the "quick check before I leave" job, and setup friction is what
 * makes people quit competitors by day two.
 */
import { Ionicons, MaterialCommunityIcons } from '@expo/vector-icons';
import * as ImageManipulator from 'expo-image-manipulator';
import * as ImagePicker from 'expo-image-picker';
import React, { useState } from 'react';
import {
  Alert,
  Image,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native';

import { ApiError, uploadOutfit } from '../api/client';
import type { Quota } from '../api/types';
import { Button, Chip, SectionLabel } from '../components/primitives';
import {
  CAPTURE_MODES,
  CONTEXT_NOTE_MAX_LENGTH,
  MAX_UPLOAD_LONGEST_EDGE,
  OCCASIONS,
  UPLOAD_JPEG_QUALITY,
  type CaptureMode,
  type Occasion,
} from '../config';
import { colors, radius, sentenceCase, space, type, weight } from '../theme';

interface Props {
  quota: Quota | null;
  onScanStarted: (outfitId: string) => void;
  onOpenUpgrade: () => void;
}

export function CaptureScreen({
  quota,
  onScanStarted,
  onOpenUpgrade,
}: Props): React.ReactElement {
  const [imageUri, setImageUri] = useState<string | null>(null);
  const [captureMode, setCaptureMode] = useState<CaptureMode>('worn');
  const [occasion, setOccasion] = useState<Occasion | null>(null);
  const [note, setNote] = useState('');
  const [isPublic, setIsPublic] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quotaExceeded, setQuotaExceeded] = useState(false);
  const { height: windowHeight } = useWindowDimensions();

  /** §4.1 — downscale before upload to cut bandwidth. */
  const prepare = async (uri: string): Promise<string> => {
    const result = await ImageManipulator.manipulateAsync(
      uri,
      [{ resize: { width: MAX_UPLOAD_LONGEST_EDGE } }],
      {
        compress: UPLOAD_JPEG_QUALITY,
        format: ImageManipulator.SaveFormat.JPEG,
      },
    );
    return result.uri;
  };

  const pickFrom = async (source: 'camera' | 'library'): Promise<void> => {
    setError(null);
    try {
      const permission =
        source === 'camera'
          ? await ImagePicker.requestCameraPermissionsAsync()
          : await ImagePicker.requestMediaLibraryPermissionsAsync();

      if (!permission.granted) {
        Alert.alert(
          'Permission needed',
          source === 'camera'
            ? 'StyleSignal needs camera access to photograph an outfit.'
            : 'StyleSignal needs photo access to read an outfit from your library.',
        );
        return;
      }

      const options: ImagePicker.ImagePickerOptions = {
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        quality: 1,
        allowsEditing: false,
      };

      const result =
        source === 'camera'
          ? await ImagePicker.launchCameraAsync(options)
          : await ImagePicker.launchImageLibraryAsync(options);

      if (result.canceled || result.assets.length === 0) return;
      const asset = result.assets[0];
      if (!asset) return;

      setImageUri(await prepare(asset.uri));
    } catch {
      setError('Could not read that photo. Try another one.');
    }
  };

  const doSubmit = async (): Promise<void> => {
    if (!imageUri) return;
    setBusy(true);
    setError(null);
    setQuotaExceeded(false);
    try {
      const created = await uploadOutfit({
        uri: imageUri,
        occasion,
        contextNote: note.trim() || null,
        captureMode,
        isPublic,
      });
      setImageUri(null);
      setNote('');
      setOccasion(null);
      setCaptureMode('worn');
      setIsPublic(false);
      onScanStarted(created.outfit_id);
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message);
        setQuotaExceeded(caught.isQuotaExceeded);
      } else {
        setError('Could not reach StyleSignal. Check your connection.');
      }
    } finally {
      setBusy(false);
    }
  };

  // §7.9-adjacent nudge: occasion is optional, but the read leans on it
  // (occasion_match has nothing to compare against without one) — so a
  // missing occasion gets a dismissible check, never a hard block.
  const submit = (): void => {
    if (!imageUri) return;
    if (!occasion) {
      Alert.alert(
        'No occasion selected',
        "StyleSignal's read is sharper with a bit of context. Submit without one?",
        [
          { text: 'Choose occasion', style: 'cancel' },
          { text: 'Submit anyway', onPress: () => void doSubmit() },
        ],
      );
      return;
    }
    void doSubmit();
  };

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView
        style={styles.flex}
        contentContainerStyle={styles.container}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.header}>
          <Text style={styles.wordmark}>StyleSignal</Text>
        </View>

        {quota ? <QuotaLine quota={quota} onOpenUpgrade={onOpenUpgrade} /> : null}

        {/* SPEC+ "read an item, not worn" (docs/spec-deviations.md) — a
            capture-time toggle, not auto-detection: cleaner mental model,
            and it lets the backend legitimately skip body-relative signals
            (proportion, focal-point-on-body) instead of faking them. */}
        <View style={styles.modeRow}>
          {CAPTURE_MODES.map((mode) => {
            const selected = captureMode === mode;
            return (
              <Pressable
                key={mode}
                onPress={() => setCaptureMode(mode)}
                style={[styles.modeOption, selected && styles.modeOptionSelected]}
                accessibilityRole="button"
                accessibilityState={{ selected }}
              >
                <Text style={[styles.modeOptionLabel, selected && styles.modeOptionLabelSelected]}>
                  {mode === 'worn' ? 'On me' : 'An item, not worn'}
                </Text>
              </Pressable>
            );
          })}
        </View>

        <Pressable
          onPress={() => void pickFrom('library')}
          style={[
            styles.preview,
            !imageUri && styles.previewEmptyContainer,
            imageUri ? { maxHeight: windowHeight * 0.42 } : null,
          ]}
          accessibilityRole="button"
          accessibilityLabel="Choose a photo"
        >
          {imageUri ? (
            <Image source={{ uri: imageUri }} style={styles.previewImage} resizeMode="cover" />
          ) : (
            <View style={styles.previewEmpty}>
              {/* Icon + caption compose as one badge, not icon-then-separate-
                  text — the glyph itself changes with capture mode: a
                  portrait silhouette for "on me" (worn on a person), a real
                  hanger for "an item, not worn" (photographed on its own). */}
              <View style={styles.previewIconBadge}>
                {captureMode === 'worn' ? (
                  <Ionicons name="person-circle-outline" size={40} color={colors.textMuted} />
                ) : (
                  <MaterialCommunityIcons name="hanger" size={36} color={colors.textMuted} />
                )}
                <Text style={styles.previewTitle}>
                  {captureMode === 'worn' ? 'Add a photo of the outfit' : 'Add a photo of the item'}
                </Text>
                <Text style={styles.previewHint}>
                  {captureMode === 'worn'
                    ? 'Full length works best.'
                    : 'A clear, well-lit shot of the piece works best.'}
                </Text>
              </View>
            </View>
          )}
        </Pressable>

        <View style={styles.sourceRow}>
          <Button
            variant="secondary"
            label="Take photo"
            onPress={() => void pickFrom('camera')}
            style={styles.sourceButton}
          />
          <View style={{ width: space.sm }} />
          <Button
            variant="secondary"
            label="Library"
            onPress={() => void pickFrom('library')}
            style={styles.sourceButton}
          />
        </View>

        <View style={styles.block}>
          <SectionLabel>Occasion · Optional</SectionLabel>
          <Text style={styles.blockHint}>Tagging a context lets the read speak to it.</Text>
          <View style={styles.chipWrap}>
            {OCCASIONS.map((value) => (
              <Chip
                key={value}
                label={sentenceCase(value)}
                selected={occasion === value}
                onPress={() => setOccasion(occasion === value ? null : value)}
              />
            ))}
          </View>
        </View>

        <View style={styles.block}>
          <SectionLabel>Anything worth knowing · Optional</SectionLabel>
          <TextInput
            style={styles.noteInput}
            placeholder="First date — want to look sharp, not like I'm trying too hard"
            placeholderTextColor={colors.textMuted}
            value={note}
            onChangeText={(value) => setNote(value.slice(0, CONTEXT_NOTE_MAX_LENGTH))}
            multiline
            maxLength={CONTEXT_NOTE_MAX_LENGTH}
          />
          <Text style={styles.counter}>
            {note.length} of {CONTEXT_NOTE_MAX_LENGTH}
          </Text>
        </View>

        <View style={styles.publicRow}>
          <View style={styles.publicCopy}>
            <Text style={styles.publicTitle}>Share for community feedback</Text>
            <Text style={styles.publicHint}>
              Off by default. When on, other members can see this outfit and
              rate it. You can turn it off again by deleting the scan.
            </Text>
          </View>
          <Switch
            value={isPublic}
            onValueChange={setIsPublic}
            trackColor={{ true: colors.accent, false: colors.border }}
            thumbColor={colors.surface}
          />
        </View>

        {error ? <Text style={styles.error}>{error}</Text> : null}
        {quotaExceeded ? (
          <Button
            variant="secondary"
            label="Upgrade to Pro"
            onPress={onOpenUpgrade}
            style={styles.upgradeButton}
          />
        ) : null}

        <Button
          label="Read this outfit"
          onPress={() => void submit()}
          disabled={!imageUri}
          busy={busy}
          style={styles.submit}
        />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function QuotaLine({
  quota,
  onOpenUpgrade,
}: {
  quota: Quota;
  onOpenUpgrade: () => void;
}): React.ReactElement {
  if (quota.scans_remaining === null) {
    return <Text style={styles.quota}>Pro — scan as often as you like.</Text>;
  }

  // §7.9 "scans-left is a subtle pill and an upgrade moment" — "get more"
  // opens the real Pro paywall (docs/spec-deviations.md #18).
  const noun = quota.scans_remaining === 1 ? 'scan' : 'scans';
  return (
    <Pressable
      onPress={onOpenUpgrade}
      style={styles.quotaPill}
      accessibilityRole="button"
      accessibilityLabel="Upgrade to Pro"
    >
      <Text style={styles.quotaPillStrong}>
        {quota.scans_remaining} {noun} left
      </Text>
      <Text style={styles.quotaPillMuted}> · get more</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.background },
  container: { padding: space.lg, paddingBottom: space.xxl },
  header: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    marginBottom: space.xs,
  },
  wordmark: { ...type.title, color: colors.text },
  quota: { ...type.meta, color: colors.textMuted, marginBottom: space.lg },
  // §7.9 "scans-left is a subtle pill and an upgrade moment".
  quotaPill: {
    flexDirection: 'row',
    alignSelf: 'flex-start',
    alignItems: 'baseline',
    backgroundColor: '#FAF2E1',
    borderRadius: radius.pill,
    paddingHorizontal: space.md,
    paddingVertical: space.xs,
    marginBottom: space.lg,
  },
  quotaPillStrong: { ...type.meta, color: colors.text, fontWeight: weight.medium },
  quotaPillMuted: { ...type.meta, color: colors.textMuted },

  // §7.9-style selected state (filled Ink, Bone text) — the same treatment
  // as occasion chips, since this is the same kind of "the user must see
  // their choice" control, just binary and full-width.
  modeRow: {
    flexDirection: 'row',
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: 'hidden',
    marginBottom: space.md,
  },
  modeOption: {
    flex: 1,
    paddingVertical: space.sm,
    alignItems: 'center',
  },
  modeOptionSelected: { backgroundColor: colors.text },
  modeOptionLabel: { ...type.meta, color: colors.textMuted, fontWeight: weight.medium },
  modeOptionLabelSelected: { color: colors.background },

  preview: {
    aspectRatio: 3 / 4,
    borderRadius: radius.lg,
    overflow: 'hidden',
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: space.md,
  },
  // §7.9 "upload card is guided, not a void" — shorter and dashed while
  // empty, so it doesn't read as a big blank space; becomes the normal
  // aspect-correct photo frame the moment a photo is chosen.
  previewEmptyContainer: {
    aspectRatio: undefined,
    height: 220,
    borderStyle: 'dashed',
    borderWidth: 1.5,
  },
  previewImage: { width: '100%', height: '100%' },
  previewEmpty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: space.lg,
  },
  // The badge that "contains" the icon + caption as one composed unit,
  // rather than an icon floating above separate text.
  previewIconBadge: {
    alignItems: 'center',
    backgroundColor: colors.background,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    paddingVertical: space.md,
    paddingHorizontal: space.lg,
    gap: space.xs,
  },
  previewTitle: { ...type.bodyMedium, color: colors.text, marginTop: space.xs },
  previewHint: { ...type.meta, color: colors.textMuted, textAlign: 'center' },

  sourceRow: { flexDirection: 'row', marginBottom: space.xl },
  sourceButton: { flex: 1 },

  block: { marginBottom: space.xl },
  blockHint: { ...type.meta, color: colors.textMuted, marginBottom: space.sm },
  chipWrap: { flexDirection: 'row', flexWrap: 'wrap' },

  noteInput: {
    ...type.body,
    color: colors.text,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: space.md,
    minHeight: 96,
    textAlignVertical: 'top',
  },
  counter: {
    ...type.meta,
    color: colors.textMuted,
    textAlign: 'right',
    marginTop: space.xs,
  },

  publicRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: space.lg,
  },
  publicCopy: { flex: 1, paddingRight: space.md },
  publicTitle: { ...type.bodyMedium, color: colors.text },
  publicHint: { ...type.meta, color: colors.textMuted, marginTop: space.xs },

  error: { ...type.meta, color: colors.systemError, marginBottom: space.md },
  upgradeButton: { marginBottom: space.md },
  submit: { marginBottom: space.sm },
});
