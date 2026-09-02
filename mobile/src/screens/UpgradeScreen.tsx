/**
 * Pro upgrade paywall — SPEC+, native IAP approved 2026-08-30 (see
 * docs/spec-deviations.md #18). Reached from the "get more" pill and from a
 * quota-exceeded error.
 *
 * Purchases are store-native (StoreKit / Play Billing via react-native-iap)
 * — StyleSignal's backend never touches card details. It only verifies the
 * finished purchase with Apple/Google and flips `user.plan` once that
 * verification comes back valid (`POST /v1/billing/verify-purchase`).
 *
 * Needs a real product with id `PRO_SUBSCRIPTION_SKU` (config.ts) configured
 * in App Store Connect and Play Console before a purchase can complete —
 * until then `subscriptions` stays empty and this screen says so rather than
 * pretending the store has something to sell.
 */
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import {
  finishTransaction,
  getReceiptDataIOS,
  useIAP,
  type Purchase,
} from 'react-native-iap';

import { ApiError, verifyPurchase } from '../api/client';
import { Button } from '../components/primitives';
import { PRO_MONTHLY_PRICE_FALLBACK, PRO_SUBSCRIPTION_SKU } from '../config';
import { colors, space, type } from '../theme';

interface Props {
  onBack: () => void;
  /** Fires once the backend confirms Pro is active — refresh quota + leave. */
  onUpgraded: () => void;
}

export function UpgradeScreen({ onBack, onUpgraded }: Props): React.ReactElement {
  const [verifying, setVerifying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handlePurchase = async (purchase: Purchase): Promise<void> => {
    setVerifying(true);
    setError(null);
    try {
      if (Platform.OS === 'ios') {
        const receiptData = await getReceiptDataIOS();
        await verifyPurchase({
          platform: 'ios',
          productId: purchase.productId,
          receiptData,
        });
      } else {
        if (!purchase.purchaseToken) {
          throw new Error('missing_purchase_token');
        }
        await verifyPurchase({
          platform: 'android',
          productId: purchase.productId,
          purchaseToken: purchase.purchaseToken,
        });
      }
      // Only finalize with the store once StyleSignal's own backend has
      // confirmed the subscription — an unfinished transaction just
      // replays / stays pending for a retry rather than getting lost.
      await finishTransaction({ purchase, isConsumable: false });
      onUpgraded();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : 'That purchase went through with the store but StyleSignal could not confirm it. Try "Restore purchases" below.',
      );
    } finally {
      setVerifying(false);
    }
  };

  const {
    connected,
    subscriptions,
    fetchProducts,
    requestPurchase,
    restorePurchases,
    getAvailablePurchases,
  } = useIAP({
    onPurchaseSuccess: (purchase) => void handlePurchase(purchase),
    onPurchaseError: (purchaseError) => {
      setVerifying(false);
      setError(purchaseError.message || 'The purchase did not go through.');
    },
  });

  useEffect(() => {
    if (connected) {
      void fetchProducts({ skus: [PRO_SUBSCRIPTION_SKU], type: 'subs' });
    }
  }, [connected, fetchProducts]);

  const subscription = subscriptions[0];
  const displayPrice = subscription?.displayPrice ?? PRO_MONTHLY_PRICE_FALLBACK;
  const androidOfferToken =
    subscription && subscription.platform === 'android'
      ? subscription.subscriptionOffers?.[0]?.offerTokenAndroid
      : undefined;
  const canPurchase =
    connected && subscription != null && (Platform.OS === 'ios' || Boolean(androidOfferToken));

  const subscribe = async (): Promise<void> => {
    setError(null);
    if (Platform.OS === 'ios') {
      await requestPurchase({
        request: { apple: { sku: PRO_SUBSCRIPTION_SKU } },
        type: 'subs',
      });
      return;
    }
    if (!androidOfferToken) return;
    await requestPurchase({
      request: {
        google: {
          skus: [PRO_SUBSCRIPTION_SKU],
          subscriptionOffers: [{ sku: PRO_SUBSCRIPTION_SKU, offerToken: androidOfferToken }],
        },
      },
      type: 'subs',
    });
  };

  const restore = async (): Promise<void> => {
    setError(null);
    setVerifying(true);
    try {
      await restorePurchases();
      await getAvailablePurchases();
    } finally {
      setVerifying(false);
    }
  };

  return (
    <View style={styles.flex}>
      <View style={styles.header}>
        <Text style={styles.title}>StyleSignal Pro</Text>
        <Pressable onPress={onBack} accessibilityRole="button">
          <Text style={styles.headerLink}>Done</Text>
        </Pressable>
      </View>

      <View style={styles.body}>
        <Text style={styles.price}>{displayPrice}</Text>
        <Text style={styles.priceHint}>Billed monthly. Cancel any time from your store account.</Text>

        <View style={styles.benefits}>
          <Text style={styles.benefit}>· Scan as often as you like</Text>
          <Text style={styles.benefit}>· Same descriptive read, no ads, no waiting on quota</Text>
        </View>

        {!connected ? (
          <Text style={styles.hint}>Connecting to the store…</Text>
        ) : subscription == null ? (
          <Text style={styles.hint}>
            Pro isn't available for purchase from this build yet — the
            "{PRO_SUBSCRIPTION_SKU}" product hasn't been published in the
            store console.
          </Text>
        ) : null}

        {error ? <Text style={styles.error}>{error}</Text> : null}

        <Button
          label="Subscribe"
          onPress={() => void subscribe()}
          disabled={!canPurchase}
          busy={verifying}
          style={styles.subscribeButton}
        />

        <Pressable onPress={() => void restore()} accessibilityRole="button">
          <Text style={styles.restoreLink}>Restore purchases</Text>
        </Pressable>

        {verifying ? <ActivityIndicator color={colors.textMuted} style={styles.spinner} /> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    paddingHorizontal: space.lg,
    paddingTop: space.lg,
    paddingBottom: space.md,
  },
  title: { ...type.title, color: colors.text },
  headerLink: { ...type.meta, color: colors.textMuted },

  body: { paddingHorizontal: space.lg, paddingTop: space.xl },
  price: { ...type.display, color: colors.text },
  priceHint: { ...type.meta, color: colors.textMuted, marginTop: space.xs, marginBottom: space.xl },

  benefits: { marginBottom: space.xl, gap: space.sm },
  benefit: { ...type.body, color: colors.text },

  hint: { ...type.meta, color: colors.textMuted, marginBottom: space.lg },
  error: { ...type.meta, color: colors.systemError, marginBottom: space.md },

  subscribeButton: { marginBottom: space.md },
  restoreLink: { ...type.meta, color: colors.textMuted, textAlign: 'center' },
  spinner: { marginTop: space.lg },
});
