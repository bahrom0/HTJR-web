import { useEffect } from 'react';
import { AnimatePresence, motion } from 'motion/react';

import { motionTransition, useAccessibleMotion } from '@shared/motion';

export function Toast({
  message,
  onDismiss,
}: Readonly<{ message: string | null; onDismiss: () => void }>) {
  const canAnimate = useAccessibleMotion();
  useEffect(() => {
    if (!message) return undefined;
    const timer = window.setTimeout(onDismiss, 4000);
    return () => window.clearTimeout(timer);
  }, [message, onDismiss]);
  return (
    <div className="ui-toast-region" aria-live="polite" aria-atomic="true">
      <AnimatePresence>
        {message ? (
          <motion.div
            className="ui-toast"
            initial={canAnimate ? { opacity: 0, y: 12 } : false}
            animate={{ opacity: 1, y: 0 }}
            exit={canAnimate ? { opacity: 0, y: 12 } : undefined}
            transition={motionTransition.enter}
          >
            {message}
            <button type="button" onClick={onDismiss} aria-label="Закрыть уведомление">
              ×
            </button>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
