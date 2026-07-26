import { Link, Outlet, useLocation } from 'react-router-dom';
import { useTranslation } from '../lib/i18n';
import { Settings } from 'lucide-react';
import { motion } from 'motion/react';

const MotionLink = motion.create(Link);

export function Layout() {
  const { t } = useTranslation();
  const location = useLocation();

  return (
    <div className="min-h-screen flex flex-col">
      <header className="sticky top-4 md:top-6 z-50 px-4 md:px-8 max-w-7xl mx-auto w-full flex justify-between items-center pointer-events-none">
        <nav className="navigation px-5 md:px-6 py-2.5 md:py-3 flex items-center gap-6 md:gap-8 pointer-events-auto">
          <MotionLink whileTap={{ scale: 0.95 }} to="/" className={`text-sm tracking-wide transition-colors ${location.pathname === '/' ? 'font-medium opacity-100' : 'opacity-60 hover:opacity-100'}`}>{t('home')}</MotionLink>
          <MotionLink whileTap={{ scale: 0.95 }} to="/documents" className={`text-sm tracking-wide transition-colors ${location.pathname.startsWith('/documents') ? 'font-medium opacity-100' : 'opacity-60 hover:opacity-100'}`}>{t('documents')}</MotionLink>
        </nav>
        
        <div className="navigation px-3 md:px-4 py-1.5 md:py-2 flex items-center gap-4 pointer-events-auto">
           <MotionLink whileTap={{ scale: 0.9 }} to="/settings" className="opacity-60 hover:opacity-100 transition-opacity p-2 block">
             <Settings className="w-5 h-5 stroke-[1.5]" />
           </MotionLink>
        </div>
      </header>

      <main className="flex-1 w-full max-w-[1440px] px-4 md:px-8 lg:px-16 mx-auto py-6 md:py-20 relative z-10">
        <Outlet />
      </main>
    </div>
  );
}
