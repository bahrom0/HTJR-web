import { useEffect, useLayoutEffect } from 'react';
import { NavLink, Outlet, ScrollRestoration, useLocation } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';

import { motionTransition, useAccessibleMotion } from '@shared/motion';
import { PwaUpdateNotice } from '@shared/pwa/PwaUpdateNotice';
import { ThemeToggle } from '@shared/theme/ThemeToggle';
import { Icon } from '@shared/ui';
import { useNetworkStatus } from '@shared/lib/useNetworkStatus';

export function AppShell() {
  const location = useLocation();
  const isOnline = useNetworkStatus();
  const isAccessRoute = location.pathname.startsWith('/access');
  const canAnimate = useAccessibleMotion();

  useLayoutEffect(() => {
    document.getElementById('main-content')?.focus();
  }, [location.pathname]);

  useEffect(() => {
    if (!isOnline && location.pathname !== '/offline') {
      document.title = 'Нет подключения — Tajik HTR Studio';
    }
  }, [isOnline, location.pathname]);

  return (
    <div className={`app-shell ${isAccessRoute ? 'app-shell--access' : ''}`}>
      <a className="skip-link" href="#main-content">
        К основному содержимому
      </a>

      {!isAccessRoute ? (
        <header className="new-navigation">
          <nav className="new-navigation__primary" aria-label="Основная навигация">
            <NavLink to="/" end>
              Главная
            </NavLink>
            <NavLink to="/documents">Документы</NavLink>
          </nav>
          <nav className="new-navigation__tools" aria-label="Настройки интерфейса">
            <NavLink to="/settings" aria-label="Настройки">
              <Icon name="settings" />
            </NavLink>
            <ThemeToggle />
          </nav>
        </header>
      ) : null}

      {!isOnline && !isAccessRoute ? (
        <NavLink className="offline-banner" to="/offline">
          Нет подключения: часть действий временно недоступна.
        </NavLink>
      ) : null}

      <main id="main-content" tabIndex={-1}>
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={location.pathname}
            className="route-stage"
            initial={canAnimate ? { opacity: 0, y: 14, filter: 'blur(4px)' } : false}
            animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            exit={canAnimate ? { opacity: 0, y: -8 } : undefined}
            transition={motionTransition.enter}
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </main>

      <PwaUpdateNotice />
      <ScrollRestoration />
    </div>
  );
}
