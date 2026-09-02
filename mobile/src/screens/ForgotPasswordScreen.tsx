/**
 * Password reset — SPEC+, see backend/docs/spec-deviations.md.
 *
 * Two steps in one screen: request a 6-digit code by email, then confirm it
 * alongside a new password. No deep-linking — the code is short enough to
 * type by hand, which also means it works today with no email provider
 * wired up (the code just gets logged server-side in dev).
 */
import React, { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  Text,
  TextInput,
  StyleSheet,
} from 'react-native';

import { ApiError, confirmPasswordReset, requestPasswordReset } from '../api/client';
import { Button } from '../components/primitives';
import { colors, space, type } from '../theme';

interface Props {
  onDone: () => void;
}

export function ForgotPasswordScreen({ onDone }: Props): React.ReactElement {
  const [step, setStep] = useState<'request' | 'confirm' | 'done'>('request');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submitRequest = async (): Promise<void> => {
    setError(null);
    setBusy(true);
    try {
      await requestPasswordReset(email.trim());
      setStep('confirm');
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

  const submitConfirm = async (): Promise<void> => {
    setError(null);
    setBusy(true);
    try {
      await confirmPasswordReset(email.trim(), code.trim(), newPassword);
      setStep('done');
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
        <Text style={styles.title}>Reset your password</Text>

        {step === 'request' ? (
          <>
            <Text style={styles.pitch}>
              Enter the email on your account and we'll send a 6-digit code to reset your
              password.
            </Text>
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
            {error ? <Text style={styles.error}>{error}</Text> : null}
            <Button
              label="Send reset code"
              onPress={() => void submitRequest()}
              busy={busy}
              disabled={email.trim().length === 0}
              style={styles.submit}
            />
          </>
        ) : null}

        {step === 'confirm' ? (
          <>
            <Text style={styles.pitch}>
              If an account exists for {email.trim()}, a code is on its way. Enter it below
              with your new password.
            </Text>
            <TextInput
              style={styles.input}
              placeholder="6-digit code"
              placeholderTextColor={colors.textMuted}
              value={code}
              onChangeText={(value) => setCode(value.replace(/[^0-9]/g, '').slice(0, 6))}
              keyboardType="number-pad"
              maxLength={6}
            />
            <TextInput
              style={styles.input}
              placeholder="New password (8 characters or more)"
              placeholderTextColor={colors.textMuted}
              value={newPassword}
              onChangeText={setNewPassword}
              secureTextEntry
              autoCapitalize="none"
              autoComplete="new-password"
            />
            {error ? <Text style={styles.error}>{error}</Text> : null}
            <Button
              label="Reset password"
              onPress={() => void submitConfirm()}
              busy={busy}
              disabled={code.trim().length !== 6 || newPassword.length < 8}
              style={styles.submit}
            />
            <Button
              variant="quiet"
              label="Send the code again"
              onPress={() => void submitRequest()}
            />
          </>
        ) : null}

        {step === 'done' ? (
          <>
            <Text style={styles.pitch}>
              Your password has been reset. Sign in with your new password.
            </Text>
            <Button label="Back to sign in" onPress={onDone} style={styles.submit} />
          </>
        ) : null}

        {step !== 'done' ? (
          <Button variant="quiet" label="Back to sign in" onPress={onDone} />
        ) : null}
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
  title: { ...type.title, color: colors.text, marginBottom: space.sm },
  pitch: { ...type.body, color: colors.textMuted, marginBottom: space.xl },
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
});
