import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AccessProvider } from '@shared/access/AccessProvider';

import HomeRoute from './HomeRoute';

vi.mock('@shared/api/client', () => ({
  getAccessSession: vi.fn(async () => ({ ok: false, error: { code: 'none', message: 'none', retryable: false, requestId: 'test' } })),
  refreshCsrfToken: vi.fn(),
  exchangeAccessCode: vi.fn(),
  logoutAccessSession: vi.fn(),
}));

describe('normalized home', () => {
  beforeEach(() => Object.defineProperty(navigator, 'onLine', { configurable: true, value: true }));

  it('shows an honest workflow and no fabricated documents', () => {
    render(<AccessProvider><MemoryRouter><HomeRoute /></MemoryRouter></AccessProvider>);
    expect(screen.getByRole('heading', { name: 'Превратите снимок страницы в проверенный документ.' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Четыре понятных этапа' })).toBeInTheDocument();
    expect(screen.getByText(/Мы не подставляем демонстрационные записи/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Начать с изображения/ })).toHaveAttribute('href', '/capture');
  });
});
