import { describe, expect, it } from 'vitest';

import { productFontStack, tajikFontStack, tajikGlyphs } from './fonts';

describe('font policy', () => {
  it('keeps Tajik glyphs out of the decorative font and has a documented system fallback', () => {
    expect(tajikGlyphs).toBe('ҒғӢӣҚқӮӯҲҳҶҷ');
    expect(productFontStack).toContain('Outfit Variable');
    expect(tajikFontStack).toContain('Segoe UI');
    expect(productFontStack).not.toContain('Reenie');
  });
});
