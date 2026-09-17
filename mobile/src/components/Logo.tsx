/**
 * The app's wordmark, as an image — SPEC+ (docs/spec-deviations.md).
 * Replaces the plain `<Text>StyleSignal</Text>` wordmark on Home and
 * Sign-in. Two fixed assets (not a single asset re-tinted at runtime,
 * since these are baked PNGs from the brand's logo pack, not vectors):
 * `logo-light.png` (dark ink + accent-blue icon, transparent background)
 * for the light theme, `logo-dark.png` (light text + accent-blue icon,
 * transparent background) for the dark theme. `isDarkMode` is resolved
 * once at launch (see theme.ts's module header for why), so this needs
 * no live theme-switching logic — a preference change already reloads
 * the whole JS engine, which re-picks the asset from scratch.
 */
import React from 'react';
import { Image, type ImageStyle, type StyleProp } from 'react-native';

import { isDarkMode } from '../theme';

const LOGO_LIGHT = require('../../assets/logo-light.png');
const LOGO_DARK = require('../../assets/logo-dark.png');

// Each source PNG was cropped tightly to its own content, so the two
// aren't quite the same aspect ratio — sized by height, width follows.
const ASPECT_RATIO = isDarkMode ? 1323 / 301 : 1380 / 272;

export function Logo({
  height = 28,
  style,
}: {
  height?: number;
  style?: StyleProp<ImageStyle>;
}): React.ReactElement {
  return (
    <Image
      source={isDarkMode ? LOGO_DARK : LOGO_LIGHT}
      style={[{ height, width: height * ASPECT_RATIO }, style]}
      resizeMode="contain"
      accessibilityLabel="StyleSignal"
    />
  );
}
