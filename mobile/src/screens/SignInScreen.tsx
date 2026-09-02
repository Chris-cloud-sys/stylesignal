import React, { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { ApiError, login, register } from '../api/client';
import { Button } from '../components/primitives';
import { colors, space, type } from '../theme';

interface Props {
  onSignedIn: () => void;
  onForgotPassword: () => void;
}

export function SignInScreen({ onSignedIn, onForgotPassword }: Props): React.ReactElement {
  const [mode, setMode] = useState<'signIn' | 'create'>('signIn');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const creating = mode === 'create';

  const submit = async (): Promise<void> => {
    setError(null);
    setBusy(true);
    try {
      if (creating) {
        await register(email.trim(), password, displayName.trim());
      } else {
        await login(email.trim(), password);
      }
      onSignedIn();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : 'Could not reach StyleSignal. Check that the gateway is running.',
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <Text style={styles.wordmark}>StyleSignal</Text>
        <Text style={styles.pitch}>
          Photograph an outfit and get an honest read on how it comes across —
          the colours, the register, the line. It describes; you decide.
        </Text>

        {creating ? (
          <TextInput
            style={styles.input}
            placeholder="Your name"
            placeholderTextColor={colors.textMuted}
            value={displayName}
            onChangeText={setDisplayName}
            autoCapitalize="words"
            autoComplete="name"
          />
        ) : null}

        <TextInput
          style={styles.input}
          placeholder="Email"
          placeholderTextColor={colors.textMuted}
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="email-address"
          autoComplete="email"
        />

        <TextInput
          style={styles.input}
          placeholder={creating ? 'Password (8 characters or more)' : 'Password'}
          placeholderTextColor={colors.textMuted}
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          autoCapitalize="none"
          autoComplete={creating ? 'new-password' : 'current-password'}
        />

        {error ? <Text style={styles.error}>{error}</Text> : null}

        <Button
          label={creating ? 'Create account' : 'Sign in'}
          onPress={() => void submit()}
          busy={busy}
          disabled={email.trim().length === 0 || password.length === 0}
          style={styles.submit}
        />

        {!creating ? (
          <Button variant="quiet" label="Forgot password?" onPress={onForgotPassword} />
        ) : null}

        <Button
          variant="quiet"
          label={
            creating
              ? 'I already have an account'
              : 'Create an account — 10 free scans a month'
          }
          onPress={() => {
            setMode(creating ? 'signIn' : 'create');
            setError(null);
          }}
        />

        <View style={styles.promiseBox}>
          <Text style={styles.promise}>
            StyleSignal is funded by subscriptions, not by selling you clothes.
            Nothing it says is bent toward a purchase.
          </Text>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.background },
  container: {
    padding: space.lg,
    paddingTop: space.xxl,
    flexGrow: 1,
    justifyContent: 'center',
  },
  wordmark: { ...type.display, color: colors.text, marginBottom: space.sm },
  pitch: {
    ...type.body,
    color: colors.textMuted,
    marginBottom: space.xl,
  },
  input: {
    ...type.body,
    color: colors.text,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    paddingHorizontal: space.md,
    paddingVertical: space.md,
    marginBottom: space.sm,
  },
  submit: { marginTop: space.md, marginBottom: space.sm },
  error: {
    ...type.meta,
    color: colors.systemError,
    marginTop: space.xs,
    marginBottom: space.sm,
  },
  promiseBox: {
    marginTop: space.xxl,
    paddingTop: space.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  promise: { ...type.meta, color: colors.textMuted },
});
