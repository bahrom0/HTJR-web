import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { deleteDocument, getDocuments, type DocumentItem } from '@entities/document';
import { useAccess } from '@shared/access/AccessProvider';
import { Button, Dialog, Icon, LoadingState, Status } from '@shared/ui';

function statusLabel(status: DocumentItem['status']) {
  return { draft: 'Черновик', processing: 'Обрабатывается', review: 'Нужна проверка', ready: 'Готов', failed: 'Ошибка' }[status];
}

export default function DocumentsRoute() {
  const navigate = useNavigate();
  const { documentId } = useParams<{ documentId?: string }>();
  const access = useAccess();
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [query, setQuery] = useState('');
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const selectedDocument = documents.find((item) => item.id === documentId) ?? null;

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setState('loading');
      void getDocuments(query, controller.signal).then((result) => {
        if (controller.signal.aborted) return;
        if (result.ok) {
          setDocuments(result.value);
          setState('ready');
        } else setState('error');
      });
    }, query ? 250 : 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  async function removeDocument(document: DocumentItem) {
    if (!access.csrfToken) return setDeleteError('Сессия устарела. Обновите страницу.');
    const result = await deleteDocument(document, access.csrfToken);
    if (!result.ok) return setDeleteError(result.error.message);
    setDocuments((items) => items.filter((item) => item.id !== document.id));
    navigate('/documents', { replace: true });
  }

  const editorLink = selectedDocument ? `/editor?documentId=${encodeURIComponent(selectedDocument.id)}` : '/editor';

  return (
    <main className="new-documents" id="main-content" tabIndex={-1}>
      <header className="new-documents__heading">
        <h1>Документы</h1>
        <Link className="ui-button ui-button--primary" to="/capture"><Icon name="scan" /> Новый документ</Link>
      </header>
      <label className="new-documents__search">
        <span className="visually-hidden">Поиск документов</span>
        <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Найти документ" />
      </label>

      {state === 'loading' ? (
        <LoadingState
          title="Загружаем документы"
          description={query ? 'Ищем документы по вашему запросу.' : 'Получаем список документов.'}
        />
      ) : null}
      {state === 'error' ? <div className="new-empty-card" role="alert"><p>Не удалось получить документы. Проверьте сервер и повторите.</p></div> : null}
      {state === 'ready' && documents.length === 0 ? (
        <div className="new-empty-card">
          <p>{query ? 'По вашему запросу ничего не найдено' : 'Документов пока нет'}</p>
          {!query ? <Link className="ui-button ui-button--secondary" to="/capture">Распознать первую страницу</Link> : null}
        </div>
      ) : null}
      {state === 'ready' && documents.length > 0 ? (
        <div className="new-documents__list">
          {documents.map((document) => (
            <article key={document.id} className="new-document-row">
              <span className="new-document-row__icon" aria-hidden="true">
                {document.previewUrl ? <img src={document.previewUrl} alt="" loading="lazy" /> : <Icon name="document" />}
              </span>
              <div className="new-document-row__copy">
                <h2>{document.title}</h2>
                <p>{new Date(document.updatedAt).toLocaleDateString('ru-RU')} · {statusLabel(document.status)}</p>
              </div>
              <Link className="ui-button ui-button--secondary" to={`/documents/${document.id}`}>Открыть</Link>
            </article>
          ))}
        </div>
      ) : null}

      <Dialog isOpen={Boolean(documentId && selectedDocument)} title={selectedDocument?.title || 'Документ'} onClose={() => navigate('/documents')}>
        {selectedDocument ? (
          <div className="new-document-dialog">
            <Status tone={selectedDocument.status === 'ready' ? 'success' : selectedDocument.status === 'failed' ? 'warning' : 'info'}>{statusLabel(selectedDocument.status)}</Status>
            <p>{selectedDocument.pageCount} стр.</p>
            {selectedDocument.previewText ? <p>{selectedDocument.previewText}</p> : null}
            {deleteError ? <p role="alert">{deleteError}</p> : null}
            <div>
              <Link className="ui-button ui-button--primary" to={editorLink}>Открыть редактор</Link>
              <Button variant="danger" onClick={() => void removeDocument(selectedDocument)}>Удалить</Button>
            </div>
          </div>
        ) : null}
      </Dialog>
    </main>
  );
}
