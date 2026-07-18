import { afterEach, describe, expect, it, vi } from 'vitest';

import healthFixture from '../../../contracts/health-live.json';
import { parseHealthLive } from './client';

afterEach(() => vi.restoreAllMocks());

describe('parseHealthLive', () => {
  it('maps the API snake_case contract to the Web projection', () => {
    expect(parseHealthLive(healthFixture)).toEqual({ status: 'ok', requestId: 'contract-test' });
  });

  it('rejects malformed contract payloads', () => {
    expect(parseHealthLive({ status: 'ok' })).toBeNull();
  });
});
