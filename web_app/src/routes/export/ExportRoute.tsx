import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { getDocumentById } from '@entities/document';
import { loadEditorState } from '@features/editor';
import { Button, Status } from '@shared/ui';

export default function ExportRoute() {
  const [searchParams] = useSearchParams();
  const documentId = searchParams.get('documentId');
  const jobId = searchParams.get('jobId');
  const stateId = documentId || jobId || undefined;
  const document = documentId ? getDocumentById(documentId) : undefined;
  const blocks = useMemo(() => loadEditorState(stateId), [stateId]);
  const [includeTitle, setIncludeTitle] = useState(true);
  const [preserveLines, setPreserveLines] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  const title = document?.title || 'Рукопись Tajik HTR';
  const body = useMemo(() => {
    const recognized = blocks.map((block) => block.editedText).join('\n');
    const normalized = preserveLines ? recognized : recognized.replace(/\r?\n+/g, ' ');
    return includeTitle ? `${title}\n\n${normalized}` : normalized;
  }, [blocks, includeTitle, preserveLines, title]);

  function download() {
    const blob = new Blob([body], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = window.document.createElement('a');
    link.href = url;
    link.download = `${title.replace(/[^\p{L}\p{N}-]+/gu, '_') || 'tajik-htr'}.txt`;
    link.click();
    URL.revokeObjectURL(url);
    setMessage('TXT-файл сохранён.');
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(body);
      setMessage('Текст скопирован.');
    } catch {
      setMessage('Не удалось скопировать текст автоматически.');
    }
  }

  return (
    <main className="new-export" id="main-content" tabIndex={-1}>
      <header className="new-export__heading">
        <div>
          <h1>Экспорт документа</h1>
          <p>Проверьте текст и выберите действие.</p>
        </div>
        <Link
          className="ui-button ui-button--secondary"
          to={`/editor${stateId ? `?jobId=${encodeURIComponent(stateId)}` : ''}`}
        >
          Назад к редактору
        </Link>
      </header>

      <div className="new-export__layout">
        <section className="new-export__options">
          <h2>Параметры</h2>
          <label>
            <input
              type="checkbox"
              checked={includeTitle}
              onChange={(event) => setIncludeTitle(event.target.checked)}
            />
            <span>
              <strong>Добавить название</strong>
              <small>Первая строка файла будет содержать название документа.</small>
            </span>
          </label>
          <label>
            <input
              type="checkbox"
              checked={preserveLines}
              onChange={(event) => setPreserveLines(event.target.checked)}
            />
            <span>
              <strong>Сохранить разрывы строк</strong>
              <small>Структура распознанной страницы останется прежней.</small>
            </span>
          </label>
          <div className="new-export__actions">
            <Button onClick={download} disabled={!body.trim()}>
              Скачать TXT
            </Button>
            <Button variant="secondary" onClick={() => void copy()} disabled={!body.trim()}>
              Копировать
            </Button>
          </div>
          {message ? <Status tone="info">{message}</Status> : null}
        </section>

        <section className="new-export__preview">
          <header>
            <h2>Предпросмотр</h2>
            <span>{body.length} символов</span>
          </header>
          <pre>{body || 'Нет текста для экспорта.'}</pre>
        </section>
      </div>
    </main>
  );
}
