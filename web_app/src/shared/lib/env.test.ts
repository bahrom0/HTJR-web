import { describe, expect, it } from 'vitest';
import '@testing-library/jest-dom/vitest';

import { readPublicEnvironment } from './env';

describe('readPublicEnvironment', () => {
  it('uses same-origin safe defaults', () => {
    expect(readPublicEnvironment({})).toEqual({
      apiBaseUrl: '/api/v1',
      appName: 'Tajik HTR Studio',
    });
  });

  it('rejects an absolute API URL', () => {
    expect(() => readPublicEnvironment({ VITE_API_BASE_URL: 'http://localhost:8000' })).toThrow(
      'same-origin path',
    );
  });
});
