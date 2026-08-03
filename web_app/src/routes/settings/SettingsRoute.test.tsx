import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ThemeProvider } from '@shared/theme';
import SettingsRoute from './SettingsRoute';

vi.mock('@shared/access/AccessProvider', () => ({
  useAccess: () => ({
    user: { name: 'Тестовый пользователь', email: 'test@example.test' },
    expiresAt: '2026-08-03T12:00:00Z',
    logout: vi.fn(),
  }),
}));

describe('SettingsRoute', () => {
  beforeEach(() => {
    localStorage.clear();
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
  });

  it('renders the account and saves appearance preferences to localStorage', () => {
    render(
      <ThemeProvider>
        <MemoryRouter>
          <SettingsRoute />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(screen.getByRole('heading', { name: 'Настройки' })).toBeInTheDocument();
    expect(screen.getByText('Тестовый пользователь')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Интерфейс' }));

    const highContrast = screen.getByRole('switch', { name: 'Высокая контрастность' });
    expect(highContrast).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(highContrast);
    expect(highContrast).toHaveAttribute('aria-checked', 'true');

    const savedSettings = JSON.parse(localStorage.getItem('htr_settings') || '{}');
    expect(savedSettings.highContrast).toBe(true);
  });

  it('clears local cache when requested', () => {
    localStorage.setItem('htr_draft_1', 'some draft content');
    render(
      <ThemeProvider>
        <MemoryRouter>
          <SettingsRoute />
        </MemoryRouter>
      </ThemeProvider>,
    );

    fireEvent.click(screen.getAllByRole('button', { name: 'Хранилище' }).at(-1)!);
    fireEvent.click(screen.getByRole('button', { name: 'Очистить кэш' }));

    expect(localStorage.getItem('htr_draft_1')).toBeNull();
    expect(screen.getByText('Локальный кэш очищен.')).toBeInTheDocument();
  });
});
