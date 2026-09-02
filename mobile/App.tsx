/**
 * StyleSignal — React Native client (spec §4.1).
 *
 * Four screens and a single-level stack, so there is no navigation library to
 * link. Swap in react-navigation when the surface grows past this; every
 * screen below already takes plain callback props rather than a navigator.
 */
import { StatusBar } from 'expo-status-bar';
import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import {
  SafeAreaProvider,
  SafeAreaView,
} from 'react-native-safe-area-context';

import { clearSession, fetchMe, loadStoredSession } from './src/api/client';
import type { Quota } from './src/api/types';
import { CaptureScreen } from './src/screens/CaptureScreen';
import { FeedScreen } from './src/screens/FeedScreen';
import { ForgotPasswordScreen } from './src/screens/ForgotPasswordScreen';
import { HistoryScreen } from './src/screens/HistoryScreen';
import { ResultScreen } from './src/screens/ResultScreen';
import { SignInScreen } from './src/screens/SignInScreen';
import { UpgradeScreen } from './src/screens/UpgradeScreen';
import { colors } from './src/theme';

type Screen =
  | { name: 'loading' }
  | { name: 'signIn' }
  | { name: 'forgotPassword' }
  | { name: 'capture' }
  | { name: 'result'; outfitId: string }
  | { name: 'history' }
  | { name: 'feed' }
  | { name: 'upgrade' };

export default function App(): React.ReactElement {
  const [screen, setScreen] = useState<Screen>({ name: 'loading' });
  const [quota, setQuota] = useState<Quota | null>(null);

  const refreshQuota = useCallback(async (): Promise<void> => {
    try {
      setQuota((await fetchMe()).quota);
    } catch {
      setQuota(null);
    }
  }, []);

  const enterApp = useCallback(async (): Promise<void> => {
    setScreen({ name: 'capture' });
    await refreshQuota();
  }, [refreshQuota]);

  useEffect(() => {
    const restore = async (): Promise<void> => {
      const signedIn = await loadStoredSession();
      if (signedIn) {
        await enterApp();
      } else {
        setScreen({ name: 'signIn' });
      }
    };
    void restore();
  }, [enterApp]);

  const signOut = useCallback(async (): Promise<void> => {
    await clearSession();
    setQuota(null);
    setScreen({ name: 'signIn' });
  }, []);

  return (
    <SafeAreaProvider>
      <StatusBar style="dark" backgroundColor={colors.background} />
      <SafeAreaView style={styles.root} edges={['top', 'left', 'right']}>
        {screen.name === 'loading' ? (
          <View style={styles.centered}>
            <ActivityIndicator color={colors.textMuted} />
          </View>
        ) : null}

        {screen.name === 'signIn' ? (
          <SignInScreen
            onSignedIn={() => void enterApp()}
            onForgotPassword={() => setScreen({ name: 'forgotPassword' })}
          />
        ) : null}

        {screen.name === 'forgotPassword' ? (
          <ForgotPasswordScreen onDone={() => setScreen({ name: 'signIn' })} />
        ) : null}

        {screen.name === 'capture' ? (
          <CaptureScreen
            quota={quota}
            onScanStarted={(outfitId) => {
              setScreen({ name: 'result', outfitId });
              void refreshQuota();
            }}
            onOpenHistory={() => setScreen({ name: 'history' })}
            onOpenFeed={() => setScreen({ name: 'feed' })}
            onOpenUpgrade={() => setScreen({ name: 'upgrade' })}
            onSignOut={() => void signOut()}
          />
        ) : null}

        {screen.name === 'result' ? (
          <ResultScreen
            outfitId={screen.outfitId}
            onDone={() => setScreen({ name: 'capture' })}
          />
        ) : null}

        {screen.name === 'history' ? (
          <HistoryScreen
            onOpen={(outfitId) => setScreen({ name: 'result', outfitId })}
            onBack={() => setScreen({ name: 'capture' })}
          />
        ) : null}

        {screen.name === 'feed' ? (
          <FeedScreen
            onBack={() => setScreen({ name: 'capture' })}
            onRated={() => void refreshQuota()}
          />
        ) : null}

        {screen.name === 'upgrade' ? (
          <UpgradeScreen
            onBack={() => setScreen({ name: 'capture' })}
            onUpgraded={() => {
              setScreen({ name: 'capture' });
              void refreshQuota();
            }}
          />
        ) : null}
      </SafeAreaView>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center' },
});
