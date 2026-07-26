import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import { ThemeProvider } from '@shared/theme';
import SettingsRoute from './SettingsRoute';

describe('SettingsRoute', () => {
  beforeEach(() => {
    localStorage.clear();
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
  });

  it('renders all 4 setting cards and saves changes to localStorage', () => {
    render(
      <ThemeProvider>
        <MemoryRouter>
          <SettingsRoute />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(screen.getByRole('heading', { name: 'Настройки системы' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Внешний вид' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Распознавание' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Хранилище' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'О приложении' })).toBeInTheDocument();

    // Check version & status
    expect(screen.getByText('Tajik HTR Studio v1.0.0')).toBeInTheDocument();
    expect(screen.getByText('Сервер на связи (онлайн)')).toBeInTheDocument();

    // Toggle high contrast
    const highContrastCheckbox = screen.getByLabelText('Высокая контрастность') as HTMLInputElement;
    expect(highContrastCheckbox.checked).toBe(false);
    fireEvent.click(highContrastCheckbox);
    expect(highContrastCheckbox.checked).toBe(true);

    const savedSettings = JSON.parse(localStorage.getItem('htr_settings') || '{}');
    expect(savedSettings.highContrast).toBe(true);
  });

  it('clears local cache when clear button is clicked', () => {
    localStorage.setItem('htr_draft_1', 'some draft content');
    render(
      <ThemeProvider>
        <MemoryRouter>
          <SettingsRoute />
        </MemoryRouter>
      </ThemeProvider>,
    );

    const clearButton = screen.getAllByRole('button', { name: 'Очистить локальный кэш' })[0];
    if (clearButton) {
      fireEvent.click(clearButton);
    }

    expect(localStorage.getItem('htr_draft_1')).toBeNull();
    expect(screen.getByText('Локальный кэш и черновики очищены.')).toBeInTheDocument();
  });
});
