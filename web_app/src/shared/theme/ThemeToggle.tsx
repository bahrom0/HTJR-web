import { useContext, useEffect, useId, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';

import { motionTransition, useAccessibleMotion } from '@shared/motion';

import { ThemeContext, type ThemePreference } from './ThemeProvider';

const labels: Readonly<Record<ThemePreference, string>> = {
  light: 'Светлая тема',
  dark: 'Тёмная тема',
  system: 'Как в системе',
};

const preferences = Object.keys(labels) as ThemePreference[];

export function ThemeToggle() {
  const theme = useContext(ThemeContext);
  const [isOpen, setIsOpen] = useState(false);
  const menuId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const canAnimate = useAccessibleMotion();

  if (!theme) throw new Error('ThemeToggle must be used inside ThemeProvider.');

  useEffect(() => {
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setIsOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setIsOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener('mousedown', closeOnOutsideClick);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('mousedown', closeOnOutsideClick);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, []);

  const selectPreference = (preference: ThemePreference) => {
    theme.setPreference(preference);
    setIsOpen(false);
    triggerRef.current?.focus();
  };

  return (
    <div ref={rootRef} className="theme-toggle">
      <button
        ref={triggerRef}
        className="theme-toggle__trigger"
        type="button"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={menuId}
        onClick={() => setIsOpen((isCurrentlyOpen) => !isCurrentlyOpen)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            setIsOpen(true);
          }
        }}
      >
        <span>{labels[theme.preference]}</span>
        <svg aria-hidden="true" viewBox="0 0 16 16" focusable="false">
          <path d="m4 6 4 4 4-4" />
        </svg>
      </button>
      <AnimatePresence>
        {isOpen ? (
          <motion.div
            id={menuId}
            className="theme-toggle__menu"
            role="listbox"
            aria-label="Тема оформления"
            initial={canAnimate ? { opacity: 0, y: -8, scale: 0.98 } : false}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={canAnimate ? { opacity: 0, y: -4, scale: 0.98 } : undefined}
            transition={motionTransition.enter}
          >
            {preferences.map((preference) => (
              <button
                key={preference}
                type="button"
                role="option"
                aria-selected={theme.preference === preference}
                onClick={() => selectPreference(preference)}
              >
                {labels[preference]}
              </button>
            ))}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
