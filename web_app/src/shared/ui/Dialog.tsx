import { useEffect, useId, useRef, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'motion/react';

import { motionTransition, useAccessibleMotion } from '@shared/motion';

export function Dialog({
  isOpen,
  title,
  onClose,
  children,
}: Readonly<{ isOpen: boolean; title: string; onClose: () => void; children: ReactNode }>) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const canAnimate = useAccessibleMotion();

  useEffect(() => {
    if (!isOpen) return undefined;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;

      const focusable = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((element) => element.getAttribute('aria-hidden') !== 'true');
      if (focusable.length === 0) {
        event.preventDefault();
        dialogRef.current?.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable.at(-1);
      const focusOutside = !dialogRef.current?.contains(document.activeElement);
      if (event.shiftKey && (document.activeElement === first || focusOutside)) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && (document.activeElement === last || focusOutside)) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      previous?.focus();
    };
  }, [isOpen, onClose]);

  return (
    <AnimatePresence>
      {isOpen ? (
        <motion.div
          className="ui-dialog-backdrop"
          role="presentation"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={canAnimate ? motionTransition.enter : { duration: 0 }}
          onMouseDown={onClose}
        >
          <motion.div
            ref={dialogRef}
            className="ui-dialog"
            role="dialog"
            tabIndex={-1}
            aria-modal="true"
            aria-labelledby={titleId}
            initial={canAnimate ? { opacity: 0, scale: 0.98 } : false}
            animate={{ opacity: 1, scale: 1 }}
            exit={canAnimate ? { opacity: 0, scale: 0.98 } : undefined}
            transition={motionTransition.enter}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="ui-dialog__header">
              <h2 id={titleId}>{title}</h2>
              <button
                ref={closeButtonRef}
                className="ui-icon-button"
                type="button"
                aria-label="Закрыть диалог"
                onClick={onClose}
              >
                ×
              </button>
            </div>
            {children}
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

export const Sheet = Dialog;
