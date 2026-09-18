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
import { ActivityIndicator, BackHandler, Linking, StyleSheet, View } from 'react-native';
import {
  SafeAreaProvider,
  SafeAreaView,
} from 'react-native-safe-area-context';

import { clearSession, fetchMe, loadStoredSession } from './src/api/client';
import type { OutfitListItem, Quota } from './src/api/types';
import { BrowseFeed } from './src/components/BrowseFeed';
import { TabBar, type TabName } from './src/components/TabBar';
import { AddProfilePictureScreen } from './src/screens/AddProfilePictureScreen';
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
import { WardrobeScreen } from './src/screens/WardrobeScreen';
import { colors, isDarkMode } from './src/theme';

type Screen =
  | { name: 'loading' }
  | { name: 'signIn' }
  | { name: 'forgotPassword' }
  | { name: 'addProfilePicture' }
  | { name: 'capture' }
  | { name: 'favorites' }
  | { name: 'history' }
  | { name: 'feed' }
  | { name: 'profile' }
  | { name: 'result'; outfitId: string }
  | { name: 'upgrade' }
  | { name: 'userProfile'; userId: string; from: TabName }
  | { name: 'insights' }
  | { name: 'wardrobe' }
  | { name: 'browse'; items: OutfitListItem[]; initialIndex: number; back: Screen };

/** The five tab screens share the persistent bottom bar; result/upgrade/
 * auth screens are full-takeover and hide it. */
const TAB_SCREENS: ReadonlySet<TabName> = new Set([
  'capture',
  'favorites',
  'feed',
  'history',
  'profile',
]);

/** SPEC+ — referral deep link (docs/spec-deviations.md). Manual parsing
 * rather than pulling in expo-linking for one query param on one known
 * scheme (`stylesignal://join?ref=CODE`, set in app.json). */
function extractReferralCode(url: string): string | null {
  const match = url.match(/[?&]ref=([^&]+)/);
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

export default function App(): React.ReactElement {
  const [screen, setScreen] = useState<Screen>({ name: 'loading' });
  const [quota, setQuota] = useState<Quota | null>(null);
  const [pendingReferralCode, setPendingReferralCode] = useState<string | null>(null);

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

  // SPEC+ — referral deep link (docs/spec-deviations.md). Only meaningful
  // pre-auth (a new person tapping a friend's invite) — the code is simply
  // handed to SignInScreen whenever it's next rendered, so if the app was
  // already open past sign-in, this is a harmless no-op rather than
  // interrupting an active session.
  useEffect(() => {
    Linking.getInitialURL().then((url) => {
      if (url) {
        const code = extractReferralCode(url);
        if (code) setPendingReferralCode(code);
      }
    });
    const subscription = Linking.addEventListener('url', ({ url }) => {
      const code = extractReferralCode(url);
      if (code) setPendingReferralCode(code);
    });
    return () => subscription.remove();
  }, []);

  const signOut = useCallback(async (): Promise<void> => {
    await clearSession();
    setQuota(null);
    setScreen({ name: 'signIn' });
  }, []);

  // SPEC+ — hardware/gesture back (docs/spec-deviations.md). This app
  // hand-rolls its own screen switcher instead of a real navigator, so
  // Android's back button/gesture did nothing on any of these screens —
  // only the on-screen "Back"/"Home" link worked, forcing a reach to the
  // top of the screen every time. One centralized handler here, reused by
  // every screen that has such a link, rather than duplicating a
  // BackHandler listener in each leaf screen component. Tab screens
  // deliberately return false (unhandled) — default Android behaviour
  // there (minimize/exit) is what users already expect on a root screen.
  useEffect(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      switch (screen.name) {
        case 'result':
          setScreen({ name: 'capture' });
          return true;
        case 'insights':
        case 'wardrobe':
          setScreen({ name: 'profile' });
          return true;
        case 'userProfile':
          setScreen({ name: screen.from } as Screen);
          return true;
        case 'browse':
          setScreen(screen.back);
          return true;
        case 'upgrade':
          setScreen({ name: 'capture' });
          return true;
        case 'forgotPassword':
          setScreen({ name: 'signIn' });
          return true;
        case 'addProfilePicture':
          // Same as its own "Skip for now" — the account already exists
          // at this point (this screen only follows a successful
          // registration), so back should enter the app, not sign out.
          void enterApp();
          return true;
        default:
          return false;
      }
    });
    return () => subscription.remove();
  }, [screen, enterApp]);

  const isTabScreen = TAB_SCREENS.has(screen.name as TabName);

  return (
    <SafeAreaProvider>
      <StatusBar style={isDarkMode ? 'light' : 'dark'} backgroundColor={colors.background} />
      <SafeAreaView style={styles.root} edges={['top', 'left', 'right']}>
        <View style={styles.content}>
          {screen.name === 'loading' ? (
            <View style={styles.centered}>
              <ActivityIndicator color={colors.textMuted} />
            </View>
          ) : null}

          {screen.name === 'signIn' ? (
            <SignInScreen
              onSignedIn={(justRegistered) =>
                justRegistered ? setScreen({ name: 'addProfilePicture' }) : void enterApp()
              }
              onForgotPassword={() => setScreen({ name: 'forgotPassword' })}
              initialReferralCode={pendingReferralCode}
            />
          ) : null}

          {screen.name === 'forgotPassword' ? (
            <ForgotPasswordScreen onDone={() => setScreen({ name: 'signIn' })} />
          ) : null}

          {screen.name === 'addProfilePicture' ? (
            <AddProfilePictureScreen onDone={() => void enterApp()} />
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
              onOpenProfile={(userId) => setScreen({ name: 'userProfile', userId, from: 'capture' })}
            />
          ) : null}

          {screen.name === 'favorites' ? (
            <FavoritesScreen
              onOpen={(outfitId) => setScreen({ name: 'result', outfitId })}
              onBrowse={(items, initialIndex) =>
                setScreen({ name: 'browse', items, initialIndex, back: screen })
              }
            />
          ) : null}

          {screen.name === 'history' ? (
            <HistoryScreen
              onOpen={(outfitId) => setScreen({ name: 'result', outfitId })}
              onBrowse={(items, initialIndex) =>
                setScreen({ name: 'browse', items, initialIndex, back: screen })
              }
            />
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
              onOpenWardrobe={() => setScreen({ name: 'wardrobe' })}
            />
          ) : null}

          {screen.name === 'insights' ? (
            <InsightsScreen onBack={() => setScreen({ name: 'profile' })} />
          ) : null}

          {screen.name === 'wardrobe' ? (
            <WardrobeScreen
              onBack={() => setScreen({ name: 'profile' })}
              onOpenOutfit={(outfitId) => setScreen({ name: 'result', outfitId })}
            />
          ) : null}

          {screen.name === 'userProfile' ? (
            <UserProfileScreen
              userId={screen.userId}
              onBack={() => setScreen({ name: screen.from } as Screen)}
              onOpenOutfit={(outfitId) => setScreen({ name: 'result', outfitId })}
              onBrowse={(items, initialIndex) =>
                setScreen({ name: 'browse', items, initialIndex, back: screen })
              }
            />
          ) : null}

          {screen.name === 'browse' ? (
            <BrowseFeed
              items={screen.items}
              initialIndex={screen.initialIndex}
              onBack={() => setScreen(screen.back)}
              onOpenProfile={(userId) => setScreen({ name: 'userProfile', userId, from: 'profile' })}
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
