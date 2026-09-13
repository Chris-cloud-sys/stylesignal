/**
 * One-time, skippable prompt shown right after account creation — SPEC+
 * (docs/spec-deviations.md). Never shown on a plain login, only once per
 * fresh registration.
 */
import * as ImagePicker from 'expo-image-picker';
import React, { useEffect, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { fetchMe, uploadAvatar } from '../api/client';
import { Avatar, Button } from '../components/primitives';
import { colors, space, type } from '../theme';

interface Props {
  onDone: () => void;
}

export function AddProfilePictureScreen({ onDone }: Props): React.ReactElement {
  const [imageUri, setImageUri] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState('');

  useEffect(() => {
    fetchMe()
      .then((me) => setDisplayName(me.user.display_name || me.user.email.split('@')[0] || '?'))
      .catch(() => undefined);
  }, []);
  const [busy, setBusy] = useState(false);

  const pick = async (): Promise<void> => {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert('Permission needed', 'StyleSignal needs photo access to set a profile picture.');
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      allowsEditing: true,
      aspect: [1, 1],
      quality: 0.9,
    });
    if (result.canceled || result.assets.length === 0) return;
    const asset = result.assets[0];
    if (asset) setImageUri(asset.uri);
  };

  const save = async (): Promise<void> => {
    if (!imageUri || busy) return;
    setBusy(true);
    try {
      await uploadAvatar(imageUri);
      onDone();
    } catch {
      Alert.alert('Could not upload that photo', 'You can add one later from Profile.');
      onDone();
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.flex}>
      <View style={styles.body}>
        <Text style={styles.title}>Add a profile picture</Text>
        <Text style={styles.hint}>
          Shown next to your name on comments and your profile. Optional — you
          can add or change this anytime from Profile.
        </Text>

        <Pressable
          onPress={() => void pick()}
          style={styles.avatarPress}
          accessibilityRole="button"
          accessibilityLabel="Choose a profile picture"
        >
          <Avatar name={displayName || '?'} uri={imageUri} size={120} />
        </Pressable>

        <Button
          label={imageUri ? 'Choose a different photo' : 'Choose a photo'}
          variant="secondary"
          onPress={() => void pick()}
          style={styles.chooseButton}
        />

        <Button
          label="Save and continue"
          onPress={() => void save()}
          disabled={!imageUri}
          busy={busy}
          style={styles.saveButton}
        />

        <Button variant="quiet" label="Skip for now" onPress={onDone} style={styles.skipButton} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.background },
  body: { flex: 1, paddingHorizontal: space.lg, paddingTop: space.xxl, alignItems: 'center' },
  title: { ...type.title, color: colors.text, textAlign: 'center' },
  hint: {
    ...type.body,
    color: colors.textMuted,
    textAlign: 'center',
    marginTop: space.sm,
    marginBottom: space.xl,
  },
  avatarPress: { padding: 0, backgroundColor: 'transparent' },
  chooseButton: { marginTop: space.lg, alignSelf: 'stretch' },
  saveButton: { marginTop: space.md, alignSelf: 'stretch' },
  skipButton: { marginTop: space.md },
});
