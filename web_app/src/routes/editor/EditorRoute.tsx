import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import {
  calculateTextStats,
  loadEditorState,
  saveEditorState,
  type LineBlock,
} from '@features/editor';
import { Button, Icon, Status } from '@shared/ui';

export default function EditorRoute() {
  const [searchParams] = useSearchParams();
  const jobId = searchParams.get('jobId');
  const documentId = searchParams.get('documentId');
  const stateId = jobId || documentId || undefined;
  const [blocks, setBlocks] = useState<LineBlock[]>(() => loadEditorState(stateId));
  const [history, setHistory] = useState<LineBlock[][]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(() => blocks[0]?.id ?? null);
  const [isDirty, setIsDirty] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(new Date());

  const selected = blocks.find((block) => block.id === selectedId) ?? blocks[0] ?? null;
  const stats = useMemo(() => calculateTextStats(blocks), [blocks]);
  const query = stateId ? `?jobId=${encodeURIComponent(stateId)}` : '';

  const updateBlocks = useCallback((recipe: (current: LineBlock[]) => LineBlock[]) => {
    setBlocks((current) => {
      setHistory((items) => [...items.slice(-29), current]);
      return recipe(current);
    });
    setIsDirty(true);
  }, []);

  useEffect(() => {
    if (!isDirty) return;
    const timer = window.setTimeout(() => {
      saveEditorState(blocks, stateId);
      setIsDirty(false);
      setLastSavedAt(new Date());
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [blocks, isDirty, stateId]);

  function updateLine(id: string, text: string) {
    updateBlocks((current) =>
      current.map((block) =>
        block.id === id
          ? {
              ...block,
              editedText: text,
              status: text === block.rawText ? 'unverified' : 'edited',
            }
          : block,
      ),
    );
  }

  function confirmLine(id: string) {
    updateBlocks((current) =>
      current.map((block) =>
        block.id === id ? { ...block, status: 'verified' } : block,
      ),
    );
  }

  function undo() {
    const previous = history.at(-1);
    if (!previous) return;
    setBlocks(previous);
    setHistory((items) => items.slice(0, -1));
    setIsDirty(true);
  }

  function save() {
    saveEditorState(blocks, stateId);
    setIsDirty(false);
    setLastSavedAt(new Date());
  }

  function moveSelection(direction: -1 | 1) {
    const index = Math.max(
      0,
      blocks.findIndex((block) => block.id === selectedId),
    );
    const next = blocks[Math.min(blocks.length - 1, Math.max(0, index + direction))];
    if (next) setSelectedId(next.id);
  }

  if (!selected) {
    return (
      <main className="new-editor new-editor--empty" id="main-content" tabIndex={-1}>
        <h1>Нет строк для проверки</h1>
        <Link className="ui-button ui-button--primary" to="/capture">
          Распознать страницу
        </Link>
      </main>
    );
  }

  return (
    <main className="new-editor" id="main-content" tabIndex={-1}>
      <header className="new-editor__heading">
        <div>
          <h1>Проверка документа</h1>
          <p>{stats.words} слов · {stats.characters} символов</p>
        </div>
        <div>
          <Status tone={isDirty ? 'warning' : 'success'}>
            {isDirty
              ? 'Сохраняем изменения'
              : `Сохранено${lastSavedAt ? ` в ${lastSavedAt.toLocaleTimeString('ru-RU')}` : ''}`}
          </Status>
          <Button variant="secondary" onClick={save}>
            Сохранить
          </Button>
          <Link className="ui-button ui-button--primary" to={`/export${query}`}>
            Экспорт
          </Link>
        </div>
      </header>

      <div className="new-editor__layout">
        <section className="new-editor__preview" aria-label="Фрагмент оригинала">
          <div className="new-editor__paper">
            <header>
              <span>LINE {selected.lineNumber}</span>
              <span>{Math.round(selected.confidence * 100)}%</span>
            </header>
            <div className="new-editor__scan-text">{selected.rawText}</div>
            <footer>
              <span>Фрагмент оригинала</span>
              <span>{selected.lineNumber} / {blocks.length}</span>
            </footer>
          </div>
        </section>

        <aside className="new-editor__lines" aria-label="Распознанные строки">
          <h2>Распознанный текст</h2>
          <div className="new-editor__line-list">
            {blocks.map((block) => (
              <label
                key={block.id}
                className={`new-editor__line ${
                  selected.id === block.id ? 'is-selected' : ''
                }`}
                onClick={() => setSelectedId(block.id)}
              >
                <span>
                  Строка {block.lineNumber}
                  <em>{block.status === 'verified' ? 'Проверена' : 'Нужна проверка'}</em>
                </span>
                <input
                  value={block.editedText}
                  onChange={(event) => updateLine(block.id, event.target.value)}
                />
              </label>
            ))}
          </div>
          <div className="new-editor__line-actions">
            <Button
              variant="quiet"
              aria-label="Предыдущая строка"
              onClick={() => moveSelection(-1)}
            >
              <Icon className="new-editor__back-icon" name="arrow" />
            </Button>
            <Button variant="secondary" onClick={() => confirmLine(selected.id)}>
              <Icon name="shield" />
              Подтвердить строку
            </Button>
            <Button
              variant="quiet"
              aria-label="Следующая строка"
              onClick={() => moveSelection(1)}
            >
              <Icon name="arrow" />
            </Button>
          </div>
          <Button variant="quiet" disabled={!history.length} onClick={undo}>
            Отменить последнее изменение
          </Button>
        </aside>
      </div>
    </main>
  );
}
