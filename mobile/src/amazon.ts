/**
 * SPEC+ (docs/spec-deviations.md) — "Shop similar" affiliate link-out.
 *
 * No product-data API call: the account behind AMAZON_ASSOCIATE_TAG isn't
 * yet PA-API/Creators-API eligible (Amazon requires 10 qualifying sales in
 * a trailing 30-day window before granting API access — confirmed against
 * the live token + searchItems endpoints, both returned AssociateNotEligible).
 * Until that clears, this builds a plain tagged Amazon search URL from the
 * detected garment's own fields (category/colour/pattern) instead of a
 * real product card. Swap in real PA-API results later behind the same
 * call site once the account is eligible.
 */
import type { Colour, Garment, GarmentCategory } from './api/types';

export const AMAZON_ASSOCIATE_TAG = 'armygymnast0f-20';

const CATEGORY_NOUNS: Record<GarmentCategory, string> = {
  top: 'top',
  bottom: 'pants',
  outerwear: 'jacket',
  dress: 'dress',
  footwear: 'shoes',
  accessory: 'accessory',
  headwear: 'hat',
};

const NAMED_COLOURS: { name: string; rgb: [number, number, number] }[] = [
  { name: 'black', rgb: [20, 20, 20] },
  { name: 'white', rgb: [245, 245, 245] },
  { name: 'gray', rgb: [128, 128, 128] },
  { name: 'navy', rgb: [20, 30, 80] },
  { name: 'blue', rgb: [40, 100, 200] },
  { name: 'teal', rgb: [0, 128, 128] },
  { name: 'green', rgb: [40, 130, 60] },
  { name: 'olive', rgb: [110, 110, 40] },
  { name: 'yellow', rgb: [225, 205, 50] },
  { name: 'orange', rgb: [220, 120, 40] },
  { name: 'red', rgb: [190, 35, 35] },
  { name: 'maroon', rgb: [110, 30, 40] },
  { name: 'pink', rgb: [225, 150, 175] },
  { name: 'purple', rgb: [110, 55, 150] },
  { name: 'brown', rgb: [105, 70, 40] },
  { name: 'beige', rgb: [210, 190, 155] },
  { name: 'cream', rgb: [245, 235, 205] },
];

function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace('#', '');
  return [
    parseInt(clean.slice(0, 2), 16),
    parseInt(clean.slice(2, 4), 16),
    parseInt(clean.slice(4, 6), 16),
  ];
}

function nearestColourName(hex: string): string {
  const [r, g, b] = hexToRgb(hex);
  let best = NAMED_COLOURS[0]!;
  let bestDistance = Infinity;
  for (const candidate of NAMED_COLOURS) {
    const [cr, cg, cb] = candidate.rgb;
    const distance = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2;
    if (distance < bestDistance) {
      bestDistance = distance;
      best = candidate;
    }
  }
  return best.name;
}

function dominantColour(colours: Colour[]): Colour | undefined {
  return [...colours].sort((a, b) => b.weight - a.weight)[0];
}

/** e.g. "Navy jacket", "Striped shirt". Used as the visible shop label. */
export function garmentShopLabel(garment: Garment): string {
  const noun = CATEGORY_NOUNS[garment.category];
  const dominant = dominantColour(garment.colors);
  const colourName = dominant ? nearestColourName(dominant.hex) : null;
  const patternWord =
    garment.pattern !== 'solid' && garment.pattern !== 'other' ? garment.pattern : null;
  const words = [colourName, patternWord, noun].filter(Boolean) as string[];
  const phrase = words.join(' ');
  return phrase.length === 0 ? noun : phrase[0]!.toUpperCase() + phrase.slice(1);
}

/** A tagged Amazon search URL — opens in the Amazon app if installed, else browser. */
export function amazonSearchUrl(garment: Garment): string {
  const query = garmentShopLabel(garment);
  return `https://www.amazon.com/s?k=${encodeURIComponent(query)}&tag=${AMAZON_ASSOCIATE_TAG}`;
}
