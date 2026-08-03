import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { getEditorDocument, type EditorDocument } from '@features/editor';
import { Button, Status } from '@shared/ui';

export default function ExportRoute() {
  const [searchParams] = useSearchParams();
  const documentId = searchParams.get('documentId');
  const [editor, setEditor] = useState<EditorDocument | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [includeTitle, setIncludeTitle] = useState(true);
  const [preserveLines, setPreserveLines] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!documentId) return;
    const controller = new AbortController();
    void getEditorDocument(documentId, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) setEditor(result.value);
      else setLoadError(result.error.message);
    });
    return () => controller.abort();
  }, [documentId]);

  const title = editor?.document.title || 'Рукопись Tajik HTR';
  const body = useMemo(() => {
    const recognized = (editor?.lines ?? []).map((block) => block.editedText).join('\n');
    const normalized = preserveLines ? recognized : recognized.replace(/\r?\n+/g, ' ');
    return includeTitle && normalized ? `${title}\n\n${normalized}` : normalized;
  }, [editor, includeTitle, preserveLines, title]);
  const unconfirmed = editor?.lines.filter((line) => line.status !== 'confirmed').length ?? 0;

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

  if (loadError || !documentId) {
    return (
      <main className="new-export" id="main-content" tabIndex={-1}>
        <div className="new-empty-card"><h1>Не удалось открыть экспорт</h1><p role="alert">{loadError || 'Документ не выбран.'}</p><Link className="ui-button ui-button--secondary" to="/documents">К документам</Link></div>
      </main>
    );
  }
  if (!editor) {
    return <main className="new-export" id="main-content" tabIndex={-1}><p role="status">Готовим текст для экспорта…</p></main>;
  }

  return (
    <main className="new-export" id="main-content" tabIndex={-1}>
      <header className="new-export__heading">
        <div><h1>Экспорт документа</h1><p>Экспортируется сохранённый на сервере текст.</p></div>
        <Link className="ui-button ui-button--secondary" to={`/editor?documentId=${encodeURIComponent(editor.document.id)}`}>Назад к редактору</Link>
      </header>
      <div className="new-export__layout">
        <section className="new-export__options">
          <h2>Параметры</h2>
          {unconfirmed > 0 ? <Status tone="warning">Не подтверждено строк: {unconfirmed}</Status> : <Status tone="success">Все строки подтверждены</Status>}
          <label><input type="checkbox" checked={includeTitle} onChange={(event) => setIncludeTitle(event.target.checked)} /><span><strong>Добавить название</strong><small>Название документа станет первой строкой файла.</small></span></label>
          <label><input type="checkbox" checked={preserveLines} onChange={(event) => setPreserveLines(event.target.checked)} /><span><strong>Сохранить разрывы строк</strong><small>Структура распознанной страницы останется прежней.</small></span></label>
          <div className="new-export__actions">
            <Button onClick={download} disabled={!body.trim()}>Скачать TXT</Button>
            <Button variant="secondary" onClick={() => void copy()} disabled={!body.trim()}>Копировать</Button>
          </div>
          {message ? <Status tone="info">{message}</Status> : null}
        </section>
        <section className="new-export__preview">
          <header><h2>Предпросмотр</h2><span>{body.length} символов</span></header>
          <pre>{body || 'Нет текста для экспорта.'}</pre>
        </section>
      </div>
    </main>
  );
}
