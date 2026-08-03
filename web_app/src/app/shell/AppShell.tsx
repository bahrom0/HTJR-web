import { useEffect, useLayoutEffect } from 'react';
import { NavLink, Outlet, ScrollRestoration, useLocation } from 'react-router-dom';
import { motion } from 'motion/react';

import { motionTransition, useAccessibleMotion } from '@shared/motion';
import { PwaUpdateNotice } from '@shared/pwa/PwaUpdateNotice';
import { ThemeToggle } from '@shared/theme/ThemeToggle';
import { Icon } from '@shared/ui';
import { useNetworkStatus } from '@shared/lib/useNetworkStatus';

export function AppShell() {
  const location = useLocation();
  const isOnline = useNetworkStatus();
  const isAccessRoute = location.pathname.startsWith('/access');
  const isProcessingRoute = location.pathname === '/processing';
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
    <div
      className={`app-shell ${isAccessRoute ? 'app-shell--access' : ''} ${
        isProcessingRoute ? 'app-shell--immersive' : ''
      }`}
    >
      <a className="skip-link" href="#main-content">
        К основному содержимому
      </a>

      {!isAccessRoute && !isProcessingRoute ? (
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
        <motion.div
          key={location.pathname}
          className="route-stage"
          initial={canAnimate ? { opacity: 0 } : false}
          animate={{ opacity: 1 }}
          transition={motionTransition.enter}
        >
          <Outlet />
        </motion.div>
      </main>

      <PwaUpdateNotice />
      <ScrollRestoration />
    </div>
  );
}
