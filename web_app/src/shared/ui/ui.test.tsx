import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Button, Dialog, Field, IconButton, Tabs, Toast } from './index';

describe('Softly UI primitives', () => {
  it('exposes semantic labels, errors and disabled state', () => {
    render(
      <>
        <Button disabled>Продолжить</Button>
        <IconButton label="Закрыть">×</IconButton>
        <Field label="Название" error="Поле обязательно" />
      </>,
    );
    expect(screen.getByRole('button', { name: 'Продолжить' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Закрыть' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Поле обязательно');
  });

  it('uses keyboard-accessible tabs and traps dialog focus until Escape closes it', () => {
    const onClose = vi.fn();
    render(
      <>
        <Tabs
          activeId="text"
          onChange={() => undefined}
          items={[{ id: 'text', label: 'Текст', panel: 'Содержимое' }]}
        />
        <Dialog isOpen title="Подтверждение" onClose={onClose}>
          <button type="button">Подтвердить</button>
        </Dialog>
      </>,
    );
    expect(screen.getByRole('tab', { name: 'Текст' })).toHaveAttribute('aria-selected', 'true');
    const close = screen.getByRole('button', { name: 'Закрыть диалог' });
    const confirm = screen.getByRole('button', { name: 'Подтвердить' });
    expect(close).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(confirm).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(close).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('announces a toast without moving focus', () => {
    render(<Toast message="Сохранено" onDismiss={() => undefined} />);
    expect(screen.getByText('Сохранено').parentElement).toHaveAttribute('aria-live', 'polite');
  });
});
