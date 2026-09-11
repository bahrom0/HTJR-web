import { useEffect, useLayoutEffect } from 'react';
import { NavLink, Outlet, ScrollRestoration, useLocation } from 'react-router-dom';
import { motion } from 'motion/react';

import { motionTransition, useAccessibleMotion } from '@shared/motion';
import { PwaUpdateNotice } from '@shared/pwa/PwaUpdateNotice';
import { useNetworkStatus } from '@shared/lib/useNetworkStatus';

import { ProjectHeader } from './ProjectHeader';

export function AppShell() {
  const location = useLocation();
  const isOnline = useNetworkStatus();
  const isLandingRoute = location.pathname === '/';
  const isDemoRoute = location.pathname === '/0';
  const isAccessRoute = location.pathname.startsWith('/access');
  const isProcessingRoute = location.pathname === '/processing';
  const isPreparationRoute = location.pathname === '/preparation';
  const isRegionsRoute = location.pathname === '/regions';
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
      className={`app-shell ${isLandingRoute ? 'app-shell--landing' : ''} ${
        isAccessRoute ? 'app-shell--access' : ''
      } ${isProcessingRoute ? 'app-shell--immersive' : ''} ${
        isPreparationRoute ? 'app-shell--preparation' : ''
      } ${isRegionsRoute ? 'app-shell--regions' : ''} ${isDemoRoute ? 'app-shell--demo' : ''}`}
    >
      <a className="skip-link" href="#main-content">
        К основному содержимому
      </a>

      {!isLandingRoute && !isAccessRoute && !isProcessingRoute && !isDemoRoute ? <ProjectHeader /> : null}

      {!isOnline && !isLandingRoute && !isAccessRoute ? (
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
