import { Link, NavLink } from 'react-router-dom';

import { ThemeToggle } from '@shared/theme/ThemeToggle';
import { Icon } from '@shared/ui';

type ProjectHeaderProps = Readonly<{
  variant?: 'app' | 'landing';
}>;

export function ProjectHeader({ variant = 'app' }: ProjectHeaderProps) {
  const isLanding = variant === 'landing';
  const homePath = isLanding ? '/' : '/app';

  return (
    <header className={`project-header project-header--${variant}`}>
      <Link className="project-header__brand" to={homePath} aria-label="TJOCR — главная">
        <span className="project-header__brand-mark" aria-hidden="true">
          <img
            className="project-header__brand-light"
            src="/tjocr-logo-header-light.png"
            alt=""
            width="160"
            height="56"
          />
          <img
            className="project-header__brand-dark"
            src="/tjocr-logo-header-dark.png"
            alt=""
            width="160"
            height="56"
          />
        </span>
        <span className="visually-hidden">TJOCR</span>
      </Link>

      {!isLanding ? (
        <nav className="project-header__navigation" aria-label="Основная навигация">
          <NavLink to="/app" end>
            Главная
          </NavLink>
          <NavLink to="/documents">Документы</NavLink>
        </nav>
      ) : (
        <span className="project-header__landing-label" aria-hidden="true">
          Распознавание таджикского текста
        </span>
      )}

      <div className="project-header__tools" aria-label="Настройки интерфейса">
        {!isLanding ? (
          <NavLink
            className="project-header__settings"
            to="/settings"
            aria-label="Настройки"
            title="Настройки"
          >
            <Icon name="settings" />
          </NavLink>
        ) : null}
        <ThemeToggle />
      </div>
    </header>
  );
}
