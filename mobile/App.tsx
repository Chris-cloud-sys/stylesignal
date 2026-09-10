/**
 * StyleSignal — React Native client (spec §4.1).
 *
 * A single-level stack plus a persistent bottom tab bar, so there is no
 * navigation library to link. Swap in react-navigation when the surface
 * grows past this; every screen below already takes plain callback props
 * rather than a navigator.
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
import { TabBar, type TabName } from './src/components/TabBar';
import { CaptureScreen } from './src/screens/CaptureScreen';
import { FavoritesScreen } from './src/screens/FavoritesScreen';
import { FeedScreen } from './src/screens/FeedScreen';
import { ForgotPasswordScreen } from './src/screens/ForgotPasswordScreen';
import { HistoryScreen } from './src/screens/HistoryScreen';
import { InsightsScreen } from './src/screens/InsightsScreen';
import { ProfileScreen } from './src/screens/ProfileScreen';
import { ResultScreen } from './src/screens/ResultScreen';
import { SignInScreen } from './src/screens/SignInScreen';
import { UpgradeScreen } from './src/screens/UpgradeScreen';
import { UserProfileScreen } from './src/screens/UserProfileScreen';
import { colors } from './src/theme';

type Screen =
  | { name: 'loading' }
  | { name: 'signIn' }
  | { name: 'forgotPassword' }
  | { name: 'capture' }
  | { name: 'favorites' }
  | { name: 'history' }
  | { name: 'feed' }
  | { name: 'profile' }
  | { name: 'result'; outfitId: string }
  | { name: 'upgrade' }
  | { name: 'userProfile'; userId: string; from: TabName }
  | { name: 'insights' };

/** The five tab screens share the persistent bottom bar; result/upgrade/
 * auth screens are full-takeover and hide it. */
const TAB_SCREENS: ReadonlySet<TabName> = new Set([
  'capture',
  'favorites',
  'feed',
  'history',
  'profile',
]);

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

  const isTabScreen = TAB_SCREENS.has(screen.name as TabName);

  return (
    <SafeAreaProvider>
      <StatusBar style="dark" backgroundColor={colors.background} />
      <SafeAreaView style={styles.root} edges={['top', 'left', 'right']}>
        <View style={styles.content}>
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
              onOpenUpgrade={() => setScreen({ name: 'upgrade' })}
            />
          ) : null}

          {screen.name === 'result' ? (
            <ResultScreen
              outfitId={screen.outfitId}
              onDone={() => setScreen({ name: 'capture' })}
              onReread={(newOutfitId) => {
                setScreen({ name: 'result', outfitId: newOutfitId });
                void refreshQuota();
              }}
            />
          ) : null}

          {screen.name === 'favorites' ? (
            <FavoritesScreen onOpen={(outfitId) => setScreen({ name: 'result', outfitId })} />
          ) : null}

          {screen.name === 'history' ? (
            <HistoryScreen onOpen={(outfitId) => setScreen({ name: 'result', outfitId })} />
          ) : null}

          {screen.name === 'feed' ? (
            <FeedScreen
              onRated={() => void refreshQuota()}
              onOpenProfile={(userId) => setScreen({ name: 'userProfile', userId, from: 'feed' })}
            />
          ) : null}

          {screen.name === 'profile' ? (
            <ProfileScreen
              onSignOut={() => void signOut()}
              onOpenUpgrade={() => setScreen({ name: 'upgrade' })}
              onOpenProfile={(userId) => setScreen({ name: 'userProfile', userId, from: 'profile' })}
              onOpenInsights={() => setScreen({ name: 'insights' })}
            />
          ) : null}

          {screen.name === 'insights' ? (
            <InsightsScreen onBack={() => setScreen({ name: 'profile' })} />
          ) : null}

          {screen.name === 'userProfile' ? (
            <UserProfileScreen
              userId={screen.userId}
              onBack={() => setScreen({ name: screen.from } as Screen)}
              onOpenOutfit={(outfitId) => setScreen({ name: 'result', outfitId })}
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
        </View>

        {isTabScreen ? (
          <TabBar
            active={screen.name as TabName}
            onSelect={(tab) => setScreen({ name: tab } as Screen)}
          />
        ) : null}
      </SafeAreaView>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  content: { flex: 1 },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center' },
});
