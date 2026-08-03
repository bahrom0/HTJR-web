import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import HomeRoute from './HomeRoute';

vi.mock('@shared/access/AccessProvider', () => ({
  useAccess: () => ({ user: { name: 'Мадина' } }),
}));

vi.mock('@entities/document', () => ({
  getDocuments: vi.fn(async () => ({ ok: true, value: [] })),
}));

describe('HomeRoute', () => {
  it('shows the real empty document state without fabricated documents', async () => {
    render(
      <MemoryRouter>
        <HomeRoute />
      </MemoryRouter>,
    );

    expect(screen.getByRole('heading', { name: /Здравствуйте, Мадина/ })).toBeInTheDocument();
    expect(await screen.findByText('Документов пока нет')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Распознать новую страницу/ })).toHaveAttribute(
      'href',
      '/capture',
    );
  });
});
