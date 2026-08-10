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
  View,
} from 'react-native';

import { ApiError, uploadOutfit } from '../api/client';
import type { Quota } from '../api/types';
import { Button, Chip, SectionLabel } from '../components/primitives';
import {
  CONTEXT_NOTE_MAX_LENGTH,
  MAX_UPLOAD_LONGEST_EDGE,
  OCCASIONS,
  UPLOAD_JPEG_QUALITY,
  type Occasion,
} from '../config';
import { colors, radius, sentenceCase, space, type } from '../theme';

interface Props {
  quota: Quota | null;
  onScanStarted: (outfitId: string) => void;
  onOpenHistory: () => void;
  onSignOut: () => void;
}

export function CaptureScreen({
  quota,
  onScanStarted,
  onOpenHistory,
  onSignOut,
}: Props): React.ReactElement {
  const [imageUri, setImageUri] = useState<string | null>(null);
  const [occasion, setOccasion] = useState<Occasion | null>(null);
  const [note, setNote] = useState('');
  const [isPublic, setIsPublic] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const submit = async (): Promise<void> => {
    if (!imageUri) return;
    setBusy(true);
    setError(null);
    try {
      const created = await uploadOutfit({
        uri: imageUri,
        occasion,
        contextNote: note.trim() || null,
        isPublic,
      });
      setImageUri(null);
      setNote('');
      setOccasion(null);
      setIsPublic(false);
      onScanStarted(created.outfit_id);
    } catch (caught) {
      if (caught instanceof ApiError && caught.isQuotaExceeded) {
        setError(caught.message);
      } else if (caught instanceof ApiError) {
        setError(caught.message);
      } else {
        setError('Could not reach StyleSignal. Check your connection.');
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView
        contentContainerStyle={styles.container}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.header}>
          <Text style={styles.wordmark}>StyleSignal</Text>
          <Pressable onPress={onOpenHistory} accessibilityRole="button">
            <Text style={styles.headerLink}>History</Text>
          </Pressable>
        </View>

        {quota ? <QuotaLine quota={quota} /> : null}

        <Pressable
          onPress={() => void pickFrom('library')}
          style={styles.preview}
          accessibilityRole="button"
          accessibilityLabel="Choose a photo"
        >
          {imageUri ? (
            <Image source={{ uri: imageUri }} style={styles.previewImage} resizeMode="cover" />
          ) : (
            <View style={styles.previewEmpty}>
              <Text style={styles.previewTitle}>Add a photo of the outfit</Text>
              <Text style={styles.previewHint}>
                Full length works best, with the whole look in frame.
              </Text>
            </View>
          )}
        </Pressable>

        <View style={styles.sourceRow}>
          <Button
            variant="secondary"
            label="Take a photo"
            onPress={() => void pickFrom('camera')}
            style={styles.sourceButton}
          />
          <View style={{ width: space.sm }} />
          <Button
            variant="secondary"
            label="Choose from library"
            onPress={() => void pickFrom('library')}
            style={styles.sourceButton}
          />
        </View>

        <View style={styles.block}>
          <SectionLabel>Occasion — optional</SectionLabel>
          <Text style={styles.blockHint}>
            Tagging a context lets the read speak to it directly.
          </Text>
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
          <SectionLabel>Anything worth knowing — optional</SectionLabel>
          <TextInput
            style={styles.noteInput}
            placeholder="Interview at a design studio, first time meeting the team…"
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

        <Button
          label="Read this outfit"
          onPress={() => void submit()}
          disabled={!imageUri}
          busy={busy}
          style={styles.submit}
        />

        <Button variant="quiet" label="Sign out" onPress={onSignOut} />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function QuotaLine({ quota }: { quota: Quota }): React.ReactElement {
  const text =
    quota.scans_remaining === null
      ? 'Pro — scan as often as you like.'
      : `${quota.scans_remaining} ${
          quota.scans_remaining === 1 ? 'scan' : 'scans'
        } left this month.`;
  return <Text style={styles.quota}>{text}</Text>;
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
  headerLink: { ...type.meta, color: colors.textMuted },
  quota: { ...type.meta, color: colors.textMuted, marginBottom: space.lg },

  preview: {
    aspectRatio: 3 / 4,
    borderRadius: radius.lg,
    overflow: 'hidden',
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: space.md,
  },
  previewImage: { width: '100%', height: '100%' },
  previewEmpty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: space.lg,
  },
  previewTitle: { ...type.bodyMedium, color: colors.text, marginBottom: space.xs },
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
  submit: { marginBottom: space.sm },
});
