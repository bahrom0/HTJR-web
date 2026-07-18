import { Link } from 'react-router-dom';

import { EmptyState, Icon } from '@shared/ui';

export default function WorkspaceRoute({
  title,
  description,
}: Readonly<{ title: string; description: string }>) {
  return (
    <section className="shell-page" aria-labelledby="workspace-title">
      <header className="page-heading"><div><p className="eyebrow">Рабочее пространство</p><h1 id="workspace-title">{title}</h1></div><Link className="page-heading__back" to="/"><Icon name="arrow" />На главную</Link></header>
      <EmptyState
        title={title}
        action={
          <Link className="ui-button ui-button--secondary" to="/capture">
            <Icon name="scan" />Начать с изображения
          </Link>
        }
      >
        {description}
      </EmptyState>
    </section>
  );
}
