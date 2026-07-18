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
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const canAnimate = useAccessibleMotion();

  useEffect(() => {
    if (!isOpen) return undefined;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
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
            className="ui-dialog"
            role="dialog"
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
