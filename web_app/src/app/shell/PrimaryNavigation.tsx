import { useState } from 'react';
import { NavLink } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';

import { motionTransition, useAccessibleMotion } from '@shared/motion';
import { Icon, type IconName } from '@shared/ui';
import { ThemeToggle } from '@shared/theme/ThemeToggle';

const navigationItems = [
  ['/', 'Главная', 'home'],
  ['/documents', 'Документы', 'document'],
  ['/settings', 'Настройки', 'settings'],
] as const;

export function PrimaryNavigation({ onLogout }: Readonly<{ onLogout: () => void }>) {
  const [isOpen, setIsOpen] = useState(false);
  const canAnimate = useAccessibleMotion();
  const closeMenu = () => setIsOpen(false);
  return (
    <nav className="primary-navigation" aria-label="Основная навигация">
      <button
        className="primary-navigation__menu"
        type="button"
        aria-label="Открыть основное меню"
        aria-expanded={isOpen}
        aria-controls="primary-navigation-links"
        onClick={() => setIsOpen((open) => !open)}
      >
        <Icon name="menu" /> <span>Меню</span>
      </button>
      <AnimatePresence initial={false}>
        <motion.div
          id="primary-navigation-links"
          className={`primary-navigation__links ${isOpen ? 'primary-navigation__links--open' : ''}`}
          initial={canAnimate ? { opacity: 0, y: -10, scale: 0.98 } : false}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={canAnimate ? { opacity: 0, y: -6, scale: 0.98 } : undefined}
          transition={motionTransition.enter}
        >
          <div className="primary-navigation__main">
            {navigationItems.map(([to, label, icon]) => (
              <NavLink key={to} to={to} end={to === '/'} onClick={closeMenu}>
                <Icon name={icon as IconName} />
                <span>{label}</span>
              </NavLink>
            ))}
            <NavLink className="primary-navigation__cta" to="/capture" onClick={closeMenu}>
              <Icon name="scan" />
              <span>Распознать</span>
            </NavLink>
          </div>
          <div className="primary-navigation__mobile-tools">
            <ThemeToggle />
            <button
              className="ui-button ui-button--quiet"
              type="button"
              onClick={() => {
                closeMenu();
                onLogout();
              }}
            >
              Выйти из сессии
            </button>
          </div>
        </motion.div>
      </AnimatePresence>
    </nav>
  );
}
