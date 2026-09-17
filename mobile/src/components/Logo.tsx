/**
 * The app's wordmark, as an image — SPEC+ (docs/spec-deviations.md).
 * Replaces the plain `<Text>StyleSignal</Text>` wordmark on Home and
 * Sign-in. Both PNGs are the same source mark (icon shape + wordmark
 * letterforms) recoloured per theme — not two different logo concepts —
 * so light/dark show the same brand mark, just the right colours for
 * each: icon → that theme's `accent`, wordmark → that theme's `text`.
 * `isDarkMode` is resolved once at launch (see theme.ts's module header
 * for why), so this needs no live theme-switching logic — a preference
 * change already reloads the whole JS engine, which re-picks the asset
 * from scratch.
 */
import React from 'react';
import { Image, type ImageStyle, type StyleProp } from 'react-native';

import { isDarkMode } from '../theme';

const LOGO_LIGHT = require('../../assets/logo-light.png');
const LOGO_DARK = require('../../assets/logo-dark.png');

// Same source crop for both, so one aspect ratio covers either asset.
const ASPECT_RATIO = 1379 / 271;

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
