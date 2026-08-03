import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import {
  calculateTextStats,
  confirmEditorLine,
  getEditorDocument,
  saveLineDraft,
  type LineBlock,
} from '@features/editor';
import { getRecognitionResult } from '@features/results/api';
import { useAccess } from '@shared/access/AccessProvider';
import { Button, Icon, Status } from '@shared/ui';

type SaveState = 'saved' | 'dirty' | 'saving' | 'error';

export default function EditorRoute() {
  const [searchParams] = useSearchParams();
  const requestedDocumentId = searchParams.get('documentId');
  const jobId = searchParams.get('jobId');
  const access = useAccess();
  const [documentId, setDocumentId] = useState<string | null>(requestedDocumentId);
  const [title, setTitle] = useState('');
  const [blocks, setBlocks] = useState<LineBlock[]>([]);
  const blocksRef = useRef(blocks);
  const [history, setHistory] = useState<LineBlock[][]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dirtyIds, setDirtyIds] = useState<Set<string>>(new Set());
  const [saveState, setSaveState] = useState<SaveState>('saved');
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [message, setMessage] = useState<string | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);

  useEffect(() => {
    blocksRef.current = blocks;
  }, [blocks]);

  useEffect(() => {
    if (requestedDocumentId || !jobId) return;
    void getRecognitionResult(jobId).then((result) => {
      if (result.ok) setDocumentId(result.value.documentId);
      else {
        setMessage(result.error.message);
        setLoadState('error');
      }
    });
  }, [jobId, requestedDocumentId]);

  const load = useCallback(() => {
    if (!documentId) {
      return () => undefined;
    }
    const controller = new AbortController();
    void getEditorDocument(documentId, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (!result.ok) {
        setMessage(result.error.message);
        setLoadState('error');
        return;
      }
      setTitle(result.value.document.title);
      setBlocks(result.value.lines);
      setSelectedId(result.value.lines[0]?.id ?? null);
      setDirtyIds(new Set());
      setSaveState('saved');
      setLoadState('ready');
    });
    return () => controller.abort();
  }, [documentId]);

  useEffect(() => load(), [load]);

  const selected = blocks.find((block) => block.id === selectedId) ?? blocks[0] ?? null;
  const stats = useMemo(() => calculateTextStats(blocks), [blocks]);

  const persistDirty = useCallback(async () => {
    if (!access.csrfToken || dirtyIds.size === 0) return false;
    setSaveState('saving');
    const ids = [...dirtyIds];
    let allSaved = true;
    for (const id of ids) {
      const line = blocksRef.current.find((item) => item.id === id);
      if (!line) continue;
      const result = await saveLineDraft(line, access.csrfToken);
      if (!result.ok) {
        setMessage(
          result.error.code === 'revision_conflict'
            ? 'Строка изменилась на сервере. Перезагрузите редактор, чтобы не потерять чужую правку.'
            : result.error.message,
        );
        setSaveState('error');
        return false;
      }
      const unchanged = blocksRef.current.find((item) => item.id === id)?.editedText === line.editedText;
      if (!unchanged) allSaved = false;
      blocksRef.current = blocksRef.current.map((item) =>
        item.id === id ? { ...item, revision: result.value.revision, status: 'edited' } : item,
      );
      setBlocks((items) =>
        items.map((item) =>
          item.id === id ? { ...item, revision: result.value.revision, status: 'edited' } : item,
        ),
      );
      if (unchanged) setDirtyIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
    setSaveState(allSaved ? 'saved' : 'dirty');
    setLastSavedAt(new Date());
    setMessage(null);
    return true;
  }, [access.csrfToken, dirtyIds]);

  useEffect(() => {
    if (dirtyIds.size === 0) return;
    const timer = window.setTimeout(() => void persistDirty(), 1200);
    return () => window.clearTimeout(timer);
  }, [dirtyIds, persistDirty]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirtyIds.size === 0 && saveState !== 'saving') return;
      event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirtyIds.size, saveState]);

  function updateLine(id: string, text: string) {
    blocksRef.current = blocksRef.current.map((block) =>
      block.id === id ? { ...block, editedText: text, status: 'edited' } : block,
    );
    setBlocks((current) => {
      setHistory((items) => [...items.slice(-29), current]);
      return current.map((block) =>
        block.id === id ? { ...block, editedText: text, status: 'edited' } : block,
      );
    });
    setDirtyIds((current) => new Set(current).add(id));
    setSaveState('dirty');
  }

  async function confirmLine(line: LineBlock) {
    let current = line;
    if (dirtyIds.has(line.id)) {
      const saved = await persistDirty();
      if (!saved) return;
      current = blocksRef.current.find((item) => item.id === line.id) ?? line;
    }
    if (!access.csrfToken) return setMessage('Сессия устарела. Обновите страницу.');
    setSaveState('saving');
    const result = await confirmEditorLine(current, access.csrfToken);
    if (!result.ok) {
      setMessage(result.error.message);
      setSaveState('error');
      return;
    }
    blocksRef.current = blocksRef.current.map((item) =>
      item.id === line.id
        ? { ...item, revision: result.value.revision, status: 'confirmed' }
        : item,
    );
    setBlocks((items) =>
      items.map((item) =>
        item.id === line.id
          ? { ...item, revision: result.value.revision, status: 'confirmed' }
          : item,
      ),
    );
    setLastSavedAt(new Date());
    setSaveState('saved');
    setMessage('Строка подтверждена.');
  }

  function undo() {
    const previous = history.at(-1);
    if (!previous) return;
    const changed = previous.filter((line, index) => line.editedText !== blocks[index]?.editedText);
    setBlocks(previous);
    setHistory((items) => items.slice(0, -1));
    setDirtyIds((current) => {
      const next = new Set(current);
      changed.forEach((line) => next.add(line.id));
      return next;
    });
    setSaveState('dirty');
  }

  function moveSelection(direction: -1 | 1) {
    const index = Math.max(0, blocks.findIndex((block) => block.id === selectedId));
    const next = blocks[Math.min(blocks.length - 1, Math.max(0, index + direction))];
    if (next) setSelectedId(next.id);
  }

  if (loadState === 'loading' && (documentId || jobId)) {
    return <main className="new-editor new-editor--empty" id="main-content" tabIndex={-1}><p role="status">Загружаем распознанные строки…</p></main>;
  }
  if (loadState === 'error' || (!documentId && !jobId)) {
    return (
      <main className="new-editor new-editor--empty" id="main-content" tabIndex={-1}>
        <h1>Не удалось открыть редактор</h1>
        <p role="alert">{message || 'Документ не выбран.'}</p>
        <Button onClick={() => { setLoadState('loading'); load(); }}>Повторить</Button>
        <Link className="ui-button ui-button--secondary" to="/documents">К документам</Link>
      </main>
    );
  }
  if (!selected) {
    return (
      <main className="new-editor new-editor--empty" id="main-content" tabIndex={-1}>
        <h1>В документе пока нет распознанных строк</h1>
        <p>Завершите распознавание, после чего здесь появятся реальные строки и их изображения.</p>
        <Link className="ui-button ui-button--primary" to="/capture">Распознать страницу</Link>
      </main>
    );
  }

  const saveLabel =
    saveState === 'saving' ? 'Сохраняем…' :
    saveState === 'error' ? 'Не удалось сохранить' :
    saveState === 'dirty' ? 'Есть несохранённые изменения' :
    `Сохранено${lastSavedAt ? ` в ${lastSavedAt.toLocaleTimeString('ru-RU')}` : ''}`;

  return (
    <main className="new-editor" id="main-content" tabIndex={-1}>
      <header className="new-editor__heading">
        <div><h1>{title || 'Проверка документа'}</h1><p>{stats.words} слов · {stats.characters} символов</p></div>
        <div>
          <Status tone={saveState === 'error' ? 'warning' : saveState === 'saved' ? 'success' : 'info'}>{saveLabel}</Status>
          <Button variant="secondary" disabled={saveState === 'saving' || dirtyIds.size === 0} onClick={() => void persistDirty()}>Сохранить</Button>
          <Link className="ui-button ui-button--primary" to={`/export?documentId=${encodeURIComponent(documentId || '')}`}>Экспорт</Link>
        </div>
      </header>
      {message ? <p role="status">{message}</p> : null}

      <div className="new-editor__layout">
        <section className="new-editor__preview" aria-label="Фрагмент оригинала">
          <figure className="new-editor__source">
            <img
              src={selected.cropUrl}
              alt={`Фрагмент рукописи, строка ${selected.lineNumber}`}
            />
            <figcaption className="visually-hidden">
              Оригинальное изображение строки {selected.lineNumber} из {blocks.length}
            </figcaption>
          </figure>
        </section>

        <aside className="new-editor__lines" aria-label="Распознанные строки">
          <h2>Распознанный текст</h2>
          <div className="new-editor__line-list">
            {blocks.map((block) => (
              <label key={block.id} className={`new-editor__line ${selected.id === block.id ? 'is-selected' : ''}`} onClick={() => setSelectedId(block.id)}>
                <span>Строка {block.lineNumber}<em>{block.status === 'confirmed' ? 'Проверена' : block.status === 'edited' ? 'Изменена' : 'Нужна проверка'}</em></span>
                <input aria-label={`Текст строки ${block.lineNumber}`} value={block.editedText} onChange={(event) => updateLine(block.id, event.target.value)} />
              </label>
            ))}
          </div>
          <div className="new-editor__line-actions">
            <Button variant="quiet" aria-label="Предыдущая строка" onClick={() => moveSelection(-1)}><Icon className="new-editor__back-icon" name="arrow" /></Button>
            <Button variant="secondary" disabled={saveState === 'saving'} onClick={() => void confirmLine(selected)}><Icon name="shield" /> Подтвердить строку</Button>
            <Button variant="quiet" aria-label="Следующая строка" onClick={() => moveSelection(1)}><Icon name="arrow" /></Button>
          </div>
          <Button variant="quiet" disabled={!history.length} onClick={undo}>Отменить последнее изменение</Button>
        </aside>
      </div>
    </main>
  );
}
