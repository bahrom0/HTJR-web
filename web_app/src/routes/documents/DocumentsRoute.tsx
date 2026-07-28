import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { motion } from 'motion/react';

import { deleteDocument, getDocuments, type DocumentItem } from '@entities/document';
import { motionTransition, useAccessibleMotion } from '@shared/motion';
import { Button, Dialog, Icon, Status } from '@shared/ui';

function statusLabel(status: DocumentItem['status']): string {
  if (status === 'completed') return 'Готов';
  if (status === 'processing') return 'Обрабатывается';
  return 'Черновик';
}

export default function DocumentsRoute() {
  const navigate = useNavigate();
  const { documentId } = useParams<{ documentId?: string }>();
  const canAnimate = useAccessibleMotion();
  const [documents, setDocuments] = useState<DocumentItem[]>(getDocuments);
  const [query, setQuery] = useState('');
  const selectedDocument = documents.find((item) => item.id === documentId) ?? null;
  const visibleDocuments = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return documents;
    return documents.filter((item) => item.title.toLowerCase().includes(normalized));
  }, [documents, query]);

  function removeDocument(id: string) {
    setDocuments(deleteDocument(id));
    navigate('/documents', { replace: true });
  }

  return (
    <main className="new-documents" id="main-content" tabIndex={-1}>
      <header className="new-documents__heading">
        <h1>Документы</h1>
        <Link className="ui-button ui-button--primary" to="/capture">
          <Icon name="scan" />
          Новый документ
        </Link>
      </header>

      <label className="new-documents__search">
        <span className="visually-hidden">Поиск документов</span>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Найти документ"
        />
      </label>

      {visibleDocuments.length === 0 ? (
        <div className="new-empty-card">
          <p>{query ? 'По вашему запросу ничего не найдено' : 'Документов пока нет'}</p>
          {!query ? (
            <Link className="ui-button ui-button--secondary" to="/capture">
              Распознать первую страницу
            </Link>
          ) : null}
        </div>
      ) : (
        <div className="new-documents__list">
          {visibleDocuments.map((document, index) => (
            <motion.article
              key={document.id}
              className="new-document-row"
              initial={canAnimate ? { opacity: 0, y: 12 } : false}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                ...motionTransition.enter,
                delay: canAnimate ? index * 0.035 : 0,
              }}
            >
              <span className="new-document-row__icon" aria-hidden="true">
                <Icon name="document" />
              </span>
              <div className="new-document-row__copy">
                <h2>{document.title}</h2>
                <p>
                  {new Date(document.updatedAt).toLocaleDateString('ru-RU')} ·{' '}
                  {statusLabel(document.status)}
                </p>
              </div>
              <Link
                className="ui-button ui-button--secondary"
                to={`/documents/${document.id}`}
              >
                Открыть
              </Link>
            </motion.article>
          ))}
        </div>
      )}

      <Dialog
        isOpen={Boolean(selectedDocument)}
        title={selectedDocument?.title || 'Документ'}
        onClose={() => navigate('/documents')}
      >
        {selectedDocument ? (
          <div className="new-document-dialog">
            <Status tone={selectedDocument.status === 'completed' ? 'success' : 'info'}>
              {statusLabel(selectedDocument.status)}
            </Status>
            <p>{selectedDocument.pageCount} стр.</p>
            {selectedDocument.previewText ? <p>{selectedDocument.previewText}</p> : null}
            <div>
              <Link
                className="ui-button ui-button--primary"
                to={`/editor?documentId=${encodeURIComponent(selectedDocument.id)}`}
              >
                Открыть редактор
              </Link>
              <Button variant="danger" onClick={() => removeDocument(selectedDocument.id)}>
                Удалить
              </Button>
            </div>
          </div>
        ) : null}
      </Dialog>
    </main>
  );
}
