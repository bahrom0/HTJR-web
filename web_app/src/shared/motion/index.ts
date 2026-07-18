import { type Transition, useReducedMotion } from 'motion/react';

export const motionDuration = {
  instant: 0.1,
  fast: 0.16,
  base: 0.24,
  slow: 0.36,
} as const;

export const motionTransition = {
  enter: { duration: motionDuration.base, ease: 'easeOut' },
  exit: { duration: motionDuration.fast, ease: 'easeIn' },
  spring: { type: 'spring', stiffness: 360, damping: 28 },
} as const satisfies Record<string, Transition>;

export function useAccessibleMotion(): boolean {
  return !useReducedMotion();
}

export const fadeVariants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -4 },
} as const;
