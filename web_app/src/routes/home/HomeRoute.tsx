import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { getDocuments, type DocumentItem } from '@entities/document';
import { useAccess } from '@shared/access/AccessProvider';
import { Icon, LoadingState } from '@shared/ui';

function statusLabel(status: DocumentItem['status']) {
  return {
    draft: 'Черновик',
    processing: 'В работе',
    review: 'На проверке',
    ready: 'Готов',
    failed: 'Ошибка',
  }[status];
}

export default function HomeRoute() {
  const access = useAccess();
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');

  useEffect(() => {
    const controller = new AbortController();
    void getDocuments('', controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) {
        setDocuments(result.value.slice(0, 4));
        setState('ready');
      } else {
        setState('error');
      }
    });
    return () => controller.abort();
  }, []);

  return (
    <section className="new-home" aria-labelledby="home-title">
      <div className="new-home__hero">
        <h1 id="home-title">
          <span>Здравствуйте, {access.user?.name || 'пользователь'}</span>
          Готовы распознать новую рукопись?
        </h1>
        <Link className="ui-button ui-button--primary new-home__cta" to="/capture">
          <Icon name="scan" /> Распознать новую страницу
        </Link>
      </div>

      <section className="new-home__recent" aria-labelledby="recent-title">
        <header>
          <h2 id="recent-title">Недавние документы</h2>
          <Link to="/documents">Посмотреть все <Icon name="arrow" /></Link>
        </header>

        {state === 'loading' ? (
          <LoadingState
            title="Загружаем документы"
            description="Получаем последние документы вашего аккаунта."
          />
        ) : null}
        {state === 'error' ? (
          <div className="new-empty-card" role="alert">
            <p>Не удалось загрузить документы.</p>
            <button className="ui-button ui-button--secondary" type="button" onClick={() => window.location.reload()}>Повторить</button>
          </div>
        ) : null}
        {state === 'ready' && documents.length === 0 ? (
          <div className="new-empty-card">
            <p>Документов пока нет</p>
            <Link className="ui-button ui-button--secondary" to="/capture">Добавить первую страницу</Link>
          </div>
        ) : null}
        {state === 'ready' && documents.length > 0 ? (
          <div className="new-home__grid">
            {documents.map((document) => (
              <div key={document.id}>
                <Link className="new-document-tile" to={`/documents/${document.id}`}>
                  <span className="new-document-tile__preview">
                    {document.previewUrl ? <img src={document.previewUrl} alt="" loading="lazy" /> : <Icon name="document" />}
                  </span>
                  <span className="new-document-tile__copy">
                    <strong>{document.title}</strong>
                    <span>{new Date(document.updatedAt).toLocaleDateString('ru-RU')}<em>{statusLabel(document.status)}</em></span>
                  </span>
                </Link>
              </div>
            ))}
          </div>
        ) : null}
      </section>
    </section>
  );
}
