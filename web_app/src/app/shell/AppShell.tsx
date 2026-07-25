import { useEffect, useLayoutEffect } from 'react';
import { Link, Outlet, ScrollRestoration, useLocation } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';

import { PwaUpdateNotice } from '@shared/pwa/PwaUpdateNotice';
import { ThemeToggle } from '@shared/theme/ThemeToggle';
import { useNetworkStatus } from '@shared/lib/useNetworkStatus';
import { useAccess } from '@shared/access/AccessProvider';
import { Button } from '@shared/ui';
import { motionTransition, useAccessibleMotion } from '@shared/motion';

import { PrimaryNavigation } from './PrimaryNavigation';

export function AppShell() {
  const location = useLocation();
  const isOnline = useNetworkStatus();
  const isAccessRoute = location.pathname === '/access';
  const access = useAccess();
  const canAnimate = useAccessibleMotion();

  useLayoutEffect(() => {
    document.getElementById('main-content')?.focus();
  }, [location.pathname]);

  useEffect(() => {
    if (!isOnline && location.pathname !== '/offline')
      document.title = 'Нет подключения — Tajik HTR Studio';
  }, [isOnline, location.pathname]);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        К основному содержимому
      </a>
      <header className={`site-header ${isAccessRoute ? 'site-header--access' : ''}`}>
        <Link className="brand" to="/">
          <span className="brand__mark" aria-hidden="true">
            <span />
          </span>
          <span>
            Tajik HTR <strong>Studio</strong>
          </span>
        </Link>
        {!isAccessRoute && access.state === 'authenticated' ? (
          <PrimaryNavigation onLogout={() => void access.logout()} />
        ) : null}
        <div className="header-actions">
          <p className="status-label">
            <span className={`status-label__dot ${isOnline ? '' : 'status-label__dot--offline'}`} />
            {isOnline
              ? access.state === 'authenticated'
                ? 'Сессия защищена'
                : 'Нет сессии'
              : 'Нет подключения'}
          </p>
          {access.state === 'authenticated' ? (
            <Button variant="quiet" onClick={() => void access.logout()}>
              Выйти
            </Button>
          ) : null}
          <ThemeToggle />
        </div>
      </header>
      {!isOnline ? (
        <Link className="offline-banner" to="/offline">
          Нет подключения: доступны только оболочка и сохранённые локально данные.
        </Link>
      ) : null}
      <main id="main-content" tabIndex={-1}>
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={location.pathname}
            className="route-stage"
            initial={canAnimate ? { opacity: 0, y: 10 } : false}
            animate={{ opacity: 1, y: 0 }}
            exit={canAnimate ? { opacity: 0, y: -6 } : undefined}
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
