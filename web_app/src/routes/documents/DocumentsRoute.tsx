import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import {
  deleteDocument,
  getDocuments,
  toggleFavoriteDocument,
  type DocumentItem,
} from '@entities/document';
import { Button, Card, Dialog, EmptyState, Field, Icon, IconButton, Status } from '@shared/ui';

type TabKey = 'all' | 'recent' | 'drafts' | 'favorites';
type ViewMode = 'grid' | 'list';

export default function DocumentsRoute() {
  const navigate = useNavigate();
  const { documentId: routeDocId } = useParams<{ documentId?: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const searchDocId = searchParams.get('documentId');

  const activeDocId = routeDocId || searchDocId;

  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [activeTab, setActiveTab] = useState<TabKey>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState<ViewMode>('grid');

  useEffect(() => {
    setDocuments(getDocuments());
  }, []);

  const handleToggleFavorite = (id: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    const updated = toggleFavoriteDocument(id);
    setDocuments(updated);
  };

  const handleDelete = (id: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    if (window.confirm('Вы уверены, что хотите удалить этот документ?')) {
      const updated = deleteDocument(id);
      setDocuments(updated);
      if (activeDocId === id) {
        closeModal();
      }
    }
  };

  const closeModal = () => {
    if (routeDocId) {
      navigate('/documents');
    } else if (searchDocId) {
      searchParams.delete('documentId');
      setSearchParams(searchParams);
    }
  };

  const selectedDocument = useMemo(() => {
    if (!activeDocId) return null;
    return documents.find((doc) => doc.id === activeDocId) || null;
  }, [documents, activeDocId]);

  const filteredDocuments = useMemo(() => {
    let result = [...documents];

    // Filter by tab
    if (activeTab === 'recent') {
      result.sort(
        (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
      );
    } else if (activeTab === 'drafts') {
      result = result.filter((doc) => doc.status === 'draft');
    } else if (activeTab === 'favorites') {
      result = result.filter((doc) => doc.isFavorite);
    }

    // Filter by search query
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      result = result.filter(
        (doc) =>
          doc.title.toLowerCase().includes(q) ||
          (doc.previewText && doc.previewText.toLowerCase().includes(q)),
      );
    }

    return result;
  }, [documents, activeTab, searchQuery]);

  const getStatusTone = (status: DocumentItem['status']) => {
    switch (status) {
      case 'completed':
        return 'success';
      case 'processing':
        return 'warning';
      case 'draft':
      default:
        return 'info';
    }
  };

  const getStatusLabel = (status: DocumentItem['status']) => {
    switch (status) {
      case 'completed':
        return 'Завершено';
      case 'processing':
        return 'В обработке';
      case 'draft':
        return 'Черновик';
    }
  };

  const formatDate = (dateStr: string) => {
    try {
      return new Date(dateStr).toLocaleDateString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      });
    } catch {
      return dateStr;
    }
  };

  return (
    <main className="documents-page" id="main-content" tabIndex={-1}>
      <header className="page-heading documents-heading">
        <div>
          <p className="eyebrow">Архив и управление</p>
          <h1>Документы Tajik HTR</h1>
          <p>
            Список всех ваших распознанных и обрабатываемых рукописных документов.
          </p>
        </div>
        <Link className="ui-button ui-button--primary" to="/capture">
          + Распознать текст
        </Link>
      </header>

      <section className="documents-toolbar">
        <div className="documents-tabs" role="tablist" aria-label="Фильтры документов">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'all'}
            className={`documents-tab ${activeTab === 'all' ? 'documents-tab--active' : ''}`}
            onClick={() => setActiveTab('all')}
          >
            Все ({documents.length})
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'recent'}
            className={`documents-tab ${activeTab === 'recent' ? 'documents-tab--active' : ''}`}
            onClick={() => setActiveTab('recent')}
          >
            Недавние
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'drafts'}
            className={`documents-tab ${activeTab === 'drafts' ? 'documents-tab--active' : ''}`}
            onClick={() => setActiveTab('drafts')}
          >
            Черновики ({documents.filter((d) => d.status === 'draft').length})
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'favorites'}
            className={`documents-tab ${activeTab === 'favorites' ? 'documents-tab--active' : ''}`}
            onClick={() => setActiveTab('favorites')}
          >
            Избранное ({documents.filter((d) => d.isFavorite).length})
          </button>
        </div>

        <div className="documents-controls">
          <div className="documents-search">
            <Field
              label="Поиск"
              placeholder="Поиск по названию..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          <div className="documents-view-toggle" role="group" aria-label="Вид отображения">
            <button
              type="button"
              className={`view-toggle-button ${viewMode === 'grid' ? 'view-toggle-button--active' : ''}`}
              onClick={() => setViewMode('grid')}
              aria-label="Отображение сеткой"
              title="Сетка"
            >
              ⊞ Сетка
            </button>
            <button
              type="button"
              className={`view-toggle-button ${viewMode === 'list' ? 'view-toggle-button--active' : ''}`}
              onClick={() => setViewMode('list')}
              aria-label="Отображение списком"
              title="Список"
            >
              ≡ Список
            </button>
          </div>
        </div>
      </section>

      {filteredDocuments.length === 0 ? (
        <EmptyState
          title="Документов пока нет"
          action={
            <Link className="ui-button ui-button--primary" to="/capture">
              Распознать первый текст
            </Link>
          }
        >
          {searchQuery
            ? 'По вашему запросу ничего не найдено.'
            : 'У вас пока нет сохраненных документов в данном разделе.'}
        </EmptyState>
      ) : (
        <div className={`documents-container documents-container--${viewMode}`}>
          {filteredDocuments.map((doc) => (
            <Card key={doc.id} className="document-card">
              <div className="document-card__header">
                <Status tone={getStatusTone(doc.status)}>
                  {getStatusLabel(doc.status)}
                </Status>
                <button
                  type="button"
                  className={`favorite-button ${doc.isFavorite ? 'favorite-button--active' : ''}`}
                  onClick={(e) => handleToggleFavorite(doc.id, e)}
                  aria-label={doc.isFavorite ? 'Удалить из избранного' : 'Добавить в избранное'}
                  title={doc.isFavorite ? 'В избранном' : 'Добавить в избранное'}
                >
                  {doc.isFavorite ? '★' : '☆'}
                </button>
              </div>

              <div className="document-card__body">
                <h3 className="document-card__title">
                  <button
                    type="button"
                    className="document-card__title-btn"
                    onClick={() => navigate(`/documents?documentId=${doc.id}`)}
                  >
                    {doc.title}
                  </button>
                </h3>
                {doc.previewText ? (
                  <p className="document-card__preview">{doc.previewText}</p>
                ) : null}
              </div>

              <div className="document-card__meta">
                <span className="document-meta-item">
                  📄 {doc.pageCount} {doc.pageCount === 1 ? 'страница' : doc.pageCount < 5 ? 'страницы' : 'страниц'}
                </span>
                <span className="document-meta-item">
                  📅 {formatDate(doc.updatedAt)}
                </span>
              </div>

              <div className="document-card__actions">
                <Link
                  className="ui-button ui-button--secondary document-action-btn"
                  to={`/editor?documentId=${encodeURIComponent(doc.id)}`}
                >
                  Открыть в редакторе
                </Link>
                <IconButton
                  label="Удалить документ"
                  className="document-delete-btn"
                  onClick={(e) => handleDelete(doc.id, e)}
                >
                  🗑
                </IconButton>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Detail Modal */}
      <Dialog
        isOpen={Boolean(selectedDocument)}
        title={selectedDocument?.title || 'Детали документа'}
        onClose={closeModal}
      >
        {selectedDocument ? (
          <div className="document-modal-content">
            <div className="document-modal-status-row">
              <Status tone={getStatusTone(selectedDocument.status)}>
                {getStatusLabel(selectedDocument.status)}
              </Status>
              <button
                type="button"
                className={`favorite-button ${selectedDocument.isFavorite ? 'favorite-button--active' : ''}`}
                onClick={() => handleToggleFavorite(selectedDocument.id)}
              >
                {selectedDocument.isFavorite ? '★ В избранном' : '☆ В избранное'}
              </button>
            </div>

            <div className="document-modal-details">
              <p><strong>Количество страниц:</strong> {selectedDocument.pageCount}</p>
              <p><strong>Дата создания:</strong> {formatDate(selectedDocument.createdAt)}</p>
              <p><strong>Последнее изменение:</strong> {formatDate(selectedDocument.updatedAt)}</p>
            </div>

            {selectedDocument.rawText || selectedDocument.previewText ? (
              <div className="document-modal-text">
                <label className="ui-field__label">Текст документа:</label>
                <pre className="document-text-box">
                  {selectedDocument.rawText || selectedDocument.previewText}
                </pre>
              </div>
            ) : null}

            <div className="document-modal-actions">
              <Link
                className="ui-button ui-button--primary"
                to={`/editor?documentId=${encodeURIComponent(selectedDocument.id)}`}
                onClick={closeModal}
              >
                Открыть в редакторе
              </Link>
              <Button
                variant="danger"
                onClick={() => handleDelete(selectedDocument.id)}
              >
                Удалить
              </Button>
              <Button variant="quiet" onClick={closeModal}>
                Закрыть
              </Button>
            </div>
          </div>
        ) : null}
      </Dialog>
    </main>
  );
}
