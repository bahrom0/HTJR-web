import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ProjectHeader } from './ProjectHeader';

vi.mock('@shared/theme/ThemeToggle', () => ({
  ThemeToggle: () => <button type="button">Сменить тему</button>,
}));

afterEach(cleanup);

describe('ProjectHeader', () => {
  it('renders the connected application navigation and settings', () => {
    render(
      <MemoryRouter initialEntries={['/documents']}>
        <ProjectHeader />
      </MemoryRouter>,
    );

    expect(screen.getByRole('banner')).toHaveClass('project-header--app');
    expect(screen.getByRole('link', { name: 'TJOCR — главная' })).toHaveAttribute('href', '/app');
    expect(screen.getByRole('link', { name: 'Документы' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Настройки' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Сменить тему' })).toBeInTheDocument();
  });

  it('keeps the public landing header focused on the brand and theme', () => {
    render(
      <MemoryRouter>
        <ProjectHeader variant="landing" />
      </MemoryRouter>,
    );

    expect(screen.getByRole('banner')).toHaveClass('project-header--landing');
    expect(screen.getByRole('link', { name: 'TJOCR — главная' })).toHaveAttribute('href', '/');
    expect(screen.queryByRole('link', { name: 'Настройки' })).not.toBeInTheDocument();
  });
});
