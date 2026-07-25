import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Button, Card, EmptyState, IconButton, Status } from '@shared/ui';

export interface DocumentPageItem {
  id: string;
  pageNumber: number;
  title: string;
  status: 'completed' | 'processing' | 'draft' | 'error';
  thumbnailUrl: string;
  updatedAt: string;
  charCount?: number;
}

const STORAGE_KEY = 'htr_organizer_pages';

const INITIAL_PAGES: DocumentPageItem[] = [
  {
    id: 'page-1',
    pageNumber: 1,
    title: 'Страница 1 (Рукопись Рудаки - Фрагмент А)',
    status: 'completed',
    thumbnailUrl:
      'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="120" height="160" viewBox="0 0 120 160" fill="%23f6f2eb"><rect width="100%" height="100%" rx="8" fill="%23f6f2eb" stroke="%23e7e2db" stroke-width="2"/><text x="12" y="32" font-family="serif" font-size="10" fill="%23292524">Ай дареғо ки он</text><text x="12" y="52" font-family="serif" font-size="10" fill="%23292524">чунон чашмон...</text><line x1="12" y1="70" x2="108" y2="70" stroke="%23e7e2db"/><line x1="12" y1="85" x2="98" y2="85" stroke="%23e7e2db"/><line x1="12" y1="100" x2="104" y2="100" stroke="%23e7e2db"/><rect x="12" y="115" width="40" height="28" rx="4" fill="%23ffb7b2" opacity="0.5"/></svg>',
    updatedAt: '2026-07-24T15:30:00.000Z',
    charCount: 248,
  },
  {
    id: 'page-2',
    pageNumber: 2,
    title: 'Страница 2 (Архивный документ 1928 г.)',
    status: 'processing',
    thumbnailUrl:
      'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="120" height="160" viewBox="0 0 120 160" fill="%23f6f2eb"><rect width="100%" height="100%" rx="8" fill="%23f6f2eb" stroke="%23e7e2db" stroke-width="2"/><text x="12" y="32" font-family="sans-serif" font-size="9" fill="%23706862">Протокол 1928г.</text><line x1="12" y1="50" x2="108" y2="50" stroke="%23a16207" stroke-dasharray="3,3"/><line x1="12" y1="65" x2="90" y2="65" stroke="%23a16207" stroke-dasharray="3,3"/><rect x="12" y="90" width="96" height="50" rx="4" fill="%23ffe4e1" opacity="0.6"/></svg>',
    updatedAt: '2026-07-25T09:15:00.000Z',
    charCount: 120,
  },
  {
    id: 'page-3',
    pageNumber: 3,
    title: 'Страница 3 (Поэма Саъди "Гулистон")',
    status: 'draft',
    thumbnailUrl:
      'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="120" height="160" viewBox="0 0 120 160" fill="%23f6f2eb"><rect width="100%" height="100%" rx="8" fill="%23f6f2eb" stroke="%23e7e2db" stroke-width="2"/><text x="12" y="32" font-family="serif" font-size="10" fill="%23706862">Минат худоро...</text><line x1="12" y1="55" x2="100" y2="55" stroke="%23e7e2db"/><line x1="12" y1="70" x2="85" y2="70" stroke="%23e7e2db"/><line x1="12" y1="85" x2="105" y2="85" stroke="%23e7e2db"/></svg>',
    updatedAt: '2026-07-25T10:00:00.000Z',
    charCount: 0,
  },
];

export default function OrganizerRoute() {
  const navigate = useNavigate();
  const [pages, setPages] = useState<DocumentPageItem[]>([]);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed) && parsed.length > 0) {
          setPages(parsed);
          return;
        }
      }
    } catch {
      // fallback
    }
    setPages(INITIAL_PAGES);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(INITIAL_PAGES));
  }, []);

  const savePages = (newPages: DocumentPageItem[]) => {
    const reindexed = newPages.map((page, idx) => ({
      ...page,
      pageNumber: idx + 1,
    }));
    setPages(reindexed);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(reindexed));
    } catch (e) {
      console.error('Failed to save pages:', e);
    }
  };

  const moveUp = (index: number) => {
    if (index <= 0) return;
    const newPages = [...pages];
    const temp = newPages[index - 1];
    newPages[index - 1] = newPages[index];
    newPages[index] = temp;
    savePages(newPages);
    showNotice(`Страница #${index + 1} перемещена на позицию #${index}`);
  };

  const moveDown = (index: number) => {
    if (index >= pages.length - 1) return;
    const newPages = [...pages];
    const temp = newPages[index + 1];
    newPages[index + 1] = newPages[index];
    newPages[index] = temp;
    savePages(newPages);
    showNotice(`Страница #${index + 1} перемещена на позицию #${index + 2}`);
  };

  const handleRescan = (pageId: string, title: string) => {
    showNotice(`Запущено обновление страницы "${title}"...`);
    setPages((prev) =>
      prev.map((p) =>
        p.id === pageId
          ? { ...p, status: 'processing', updatedAt: new Date().toISOString() }
          : p,
      ),
    );
    setTimeout(() => {
      setPages((prev) => {
        const updated = prev.map((p) =>
          p.id === pageId
            ? { ...p, status: 'completed' as const, updatedAt: new Date().toISOString() }
            : p,
        );
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
        } catch {}
        return updated;
      });
      showNotice(`Страница "${title}" успешно обновлена!`);
    }, 1200);
  };

  const handleDeletePage = (pageId: string) => {
    const pageToDelete = pages.find((p) => p.id === pageId);
    if (!pageToDelete) return;
    if (window.confirm(`Вы действительно хотите удалить страницу #${pageToDelete.pageNumber}?`)) {
      const filtered = pages.filter((p) => p.id !== pageId);
      savePages(filtered);
      showNotice(`Страница #${pageToDelete.pageNumber} была удалена`);
    }
  };

  const showNotice = (msg: string) => {
    setActionMessage(msg);
    setTimeout(() => {
      setActionMessage((curr) => (curr === msg ? null : curr));
    }, 3000);
  };

  const getStatusTone = (status: DocumentPageItem['status']) => {
    switch (status) {
      case 'completed':
        return 'success';
      case 'processing':
        return 'warning';
      case 'error':
        return 'danger';
      case 'draft':
      default:
        return 'info';
    }
  };

  const getStatusLabel = (status: DocumentPageItem['status']) => {
    switch (status) {
      case 'completed':
        return 'Распознано';
      case 'processing':
        return 'В обработке';
      case 'error':
        return 'Ошибка';
      case 'draft':
      default:
        return 'Черновик';
    }
  };

  return (
    <main className="organizer-page" id="main-content" tabIndex={-1}>
      <header className="page-heading organizer-heading">
        <div>
          <p className="eyebrow">Мультистраничный документ</p>
          <h1>Организатор страниц</h1>
          <p>
            Управление порядком, статусами и составом страниц рукописного документа.
          </p>
        </div>

        <div className="organizer-heading__actions">
          <Button
            variant="secondary"
            onClick={() => navigate('/capture')}
          >
            ➕ Добавить страницу
          </Button>
          <Button
            variant="primary"
            onClick={() => navigate('/editor')}
          >
            📝 Перейти к редактору
          </Button>
        </div>
      </header>

      {actionMessage ? (
        <div className="organizer-toast-banner" role="status" aria-live="polite">
          <span>ℹ️</span> {actionMessage}
        </div>
      ) : null}

      <div className="organizer-stats-bar">
        <span className="organizer-stats-item">
          <strong>Всего страниц:</strong> {pages.length}
        </span>
        <span className="organizer-stats-item">
          <strong>Распознано:</strong> {pages.filter((p) => p.status === 'completed').length}
        </span>
        <span className="organizer-stats-item">
          <strong>В обработке:</strong> {pages.filter((p) => p.status === 'processing').length}
        </span>
      </div>

      {pages.length === 0 ? (
        <EmptyState
          title="Страниц пока нет"
          action={
            <Link className="ui-button ui-button--primary" to="/capture">
              Сделать снимок / Загрузить страницу
            </Link>
          }
        >
          Все страницы документа были удалены. Добавьте новые страницы для продолжения работы.
        </EmptyState>
      ) : (
        <div className="organizer-list" role="list" aria-label="Список страниц документа">
          {pages.map((page, index) => (
            <Card key={page.id} className="organizer-item">
              <div className="organizer-item__drag">
                <span className="organizer-item__number">#{page.pageNumber}</span>
                <div className="organizer-item__reorder-btns">
                  <IconButton
                    label={`Переместить страницу ${page.pageNumber} вверх`}
                    disabled={index === 0}
                    onClick={() => moveUp(index)}
                    className="reorder-btn"
                  >
                    ▲ Вверх
                  </IconButton>
                  <IconButton
                    label={`Переместить страницу ${page.pageNumber} вниз`}
                    disabled={index === pages.length - 1}
                    onClick={() => moveDown(index)}
                    className="reorder-btn"
                  >
                    ▼ Вниз
                  </IconButton>
                </div>
              </div>

              <div className="organizer-item__thumb-wrapper">
                <img
                  src={page.thumbnailUrl}
                  alt={`Миниатюра страницы ${page.pageNumber}`}
                  className="organizer-item__thumb"
                />
              </div>

              <div className="organizer-item__info">
                <div className="organizer-item__title-row">
                  <h3 className="organizer-item__title">{page.title}</h3>
                  <Status tone={getStatusTone(page.status)}>
                    {getStatusLabel(page.status)}
                  </Status>
                </div>

                <div className="organizer-item__meta">
                  <span>Обновлено: {new Date(page.updatedAt).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</span>
                  {page.charCount ? <span> • {page.charCount} символов</span> : null}
                </div>
              </div>

              <div className="organizer-item__actions">
                <Button
                  variant="secondary"
                  onClick={() => handleRescan(page.id, page.title)}
                  title="Обновить или переснять изображение страницы"
                >
                  📸 Переснять / Обновить
                </Button>
                <Button
                  variant="danger"
                  onClick={() => handleDeletePage(page.id)}
                  title="Удалить страницу из состава документа"
                >
                  🗑 Удалить страницу
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </main>
  );
}
