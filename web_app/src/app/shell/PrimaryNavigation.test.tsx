import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { ThemeProvider } from '@shared/theme/ThemeProvider';

import { PrimaryNavigation } from './PrimaryNavigation';

describe('responsive primary navigation', () => {
  it('exposes labeled destinations and session actions', () => {
    const onLogout = vi.fn();
    render(
      <ThemeProvider>
        <MemoryRouter>
          <PrimaryNavigation onLogout={onLogout} />
        </MemoryRouter>
      </ThemeProvider>,
    );
    const menu = screen.getByRole('button', { name: 'Открыть основное меню' });
    expect(menu).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(menu);
    expect(menu).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('link', { name: 'Главная' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Распознать' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Выйти из сессии' }));
    expect(onLogout).toHaveBeenCalledOnce();
  });
});
