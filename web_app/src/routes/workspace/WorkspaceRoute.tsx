import { Link, useLocation } from 'react-router-dom';

import { isUuid } from '@shared/api/client';
import { ThemeToggle } from '@shared/theme/ThemeToggle';
import { Card, EmptyState, Icon, Status } from '@shared/ui';

function recognitionHandoffJobId(value: unknown): string | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const job = (value as { recognitionJob?: unknown }).recognitionJob;
  if (typeof job !== 'object' || job === null || Array.isArray(job)) return null;
  const snapshot = job as { id?: unknown; state?: unknown; stage?: unknown };
  return snapshot.state === 'queued' && snapshot.stage === 'queued' && isUuid(snapshot.id)
    ? snapshot.id
    : null;
}

export default function WorkspaceRoute({
  title,
  description,
}: Readonly<{ title: string; description: string }>) {
  const location = useLocation();
  const recognitionJobId =
    title === 'Проверка регионов' ? recognitionHandoffJobId(location.state) : null;

  if (title === 'Документы') {
    return (
      <section className="shell-page documents-page" aria-labelledby="workspace-title">
        <header className="page-heading">
          <div>
            <p className="eyebrow">Архив работы</p>
            <h1 id="workspace-title">Документы</h1>
          </div>
          <Link className="page-heading__back" to="/">
            На главную
          </Link>
        </header>
        <Card className="documents-page__empty">
          <Icon name="document" />
          <div>
            <h2>Сохранённые страницы появятся здесь</h2>
            <p>
              После загрузки документ сохраняется на сервере. Список, поиск и версии будут показаны
              здесь, когда станет доступен документный API.
            </p>
          </div>
        </Card>
      </section>
    );
  }

  if (title === 'Настройки и приватность') {
    return (
      <section className="shell-page settings-page" aria-labelledby="workspace-title">
        <header className="page-heading">
          <div>
            <p className="eyebrow">Внешний вид и данные</p>
            <h1 id="workspace-title">Настройки</h1>
          </div>
          <Link className="page-heading__back" to="/">
            На главную
          </Link>
        </header>
        <Card className="settings-page__theme">
          <div>
            <p className="eyebrow">Оформление</p>
            <h2>Тема интерфейса</h2>
            <p>Выберите светлую, тёмную или системную тему. Настройка применяется сразу.</p>
          </div>
          <ThemeToggle />
        </Card>
        <Card>
          <p className="eyebrow">Приватность</p>
          <h2>Изображения остаются на вашем сервере</h2>
          <p>
            Управление сроком хранения и удалением данных появится вместе с отдельным privacy API.
            Пока этот экран не выдаёт неработающие кнопки.
          </p>
        </Card>
      </section>
    );
  }

  return (
    <section className="shell-page" aria-labelledby="workspace-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Рабочее пространство</p>
          <h1 id="workspace-title">{title}</h1>
        </div>
        <Link className="page-heading__back" to="/">
          <Icon name="arrow" />
          На главную
        </Link>
      </header>
      {recognitionJobId ? (
        <div role="status">
          <Status tone="info">
            Задача поиска строк создана. CRAFT выполнится worker-процессом; после этого области
            нужно проверить и подтвердить перед распознаванием текста.
          </Status>
        </div>
      ) : null}
      <EmptyState
        title={title}
        action={
          <Link className="ui-button ui-button--secondary" to="/capture">
            <Icon name="scan" />
            Начать с изображения
          </Link>
        }
      >
        {description}
      </EmptyState>
    </section>
  );
}
