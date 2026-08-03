import { describe, expect, it } from 'vitest';

import contract from '../../../contracts/openapi.v1.json';

type JsonRecord = Record<string, unknown>;

function record(value: unknown): JsonRecord {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new TypeError('Expected a JSON object');
  }
  return value as JsonRecord;
}

describe('API v1 contract snapshot', () => {
  const root = record(contract);
  const paths = record(root.paths);
  const components = record(root.components);
  const schemas = record(components.schemas);

  it('uses the canonical access path and same-origin server', () => {
    expect(paths['/api/v1/access/register']).toBeDefined();
    expect(paths['/api/v1/access/login']).toBeDefined();
    expect(paths['/api/v1/access/exchange-code']).toBeUndefined();
    expect(paths['/api/v1/access/exchange']).toBeUndefined();
    expect(root.servers).toEqual([{ url: '/', description: 'Same-origin deployment' }]);
  });

  it('publishes every resource family without pretending planned operations are live', () => {
    for (const path of [
      '/api/v1/documents/{document_id}',
      '/api/v1/pages/{page_id}',
      '/api/v1/pages/{page_id}/regions',
      '/api/v1/text-lines/{text_line_id}',
      '/api/v1/text-lines/{text_line_id}/corrections',
      '/api/v1/documents/{document_id}/exports',
      '/api/v1/diagnostics',
    ]) {
      expect(paths[path]).toBeDefined();
    }
    const diagnostics = record(paths['/api/v1/diagnostics']);
    expect(record(diagnostics.get)['x-implementation-status']).toBe('planned');
  });

  it('keeps raw, suggested and confirmed text as separate contract fields', () => {
    const textLine = record(schemas.TextLine);
    const properties = record(textLine.properties);
    expect(properties.raw_text).toBeDefined();
    expect(properties.suggested_text).toBeDefined();
    expect(properties.confirmed_text).toBeDefined();
  });

  it('declares UUID identifiers and ISO date-time timestamps', () => {
    const document = record(schemas.Document);
    const properties = record(document.properties);
    expect(record(properties.id).format).toBe('uuid');
    expect(record(properties.created_at).format).toBe('date-time');
    expect(record(properties.updated_at).format).toBe('date-time');
  });
});
