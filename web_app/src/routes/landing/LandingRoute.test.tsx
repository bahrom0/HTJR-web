import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import LandingRoute from './LandingRoute';

vi.mock('@shared/theme/ThemeToggle', () => ({
  ThemeToggle: () => <button type="button">Сменить тему</button>,
}));

describe('LandingRoute', () => {
  it('presents the product and opens the protected application route', () => {
    render(
      <MemoryRouter>
        <LandingRoute />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole('heading', { name: 'Рукописи становятся редактируемым текстом.' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Запустить приложение/ })).toHaveAttribute(
      'href',
      '/app',
    );
    expect(screen.getByRole('button', { name: 'Сменить тему' })).toBeInTheDocument();
  });
});
