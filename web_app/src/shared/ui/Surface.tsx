import { type HTMLAttributes, type ReactNode } from 'react';

export function Card({ className = '', ...props }: HTMLAttributes<HTMLElement>) {
  return <section className={`ui-card ${className}`.trim()} {...props} />;
}

export function Badge({
  tone = 'neutral',
  children,
}: Readonly<{
  tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'info';
  children: ReactNode;
}>) {
  return <span className={`ui-badge ui-badge--${tone}`}>{children}</span>;
}

export function Status({
  tone = 'info',
  children,
}: Readonly<{ tone?: 'success' | 'warning' | 'danger' | 'info'; children: ReactNode }>) {
  return (
    <p className={`ui-status ui-status--${tone}`}>
      <span aria-hidden="true" />
      {children}
    </p>
  );
}

export function Skeleton({ className = '' }: Readonly<{ className?: string }>) {
  return <span className={`ui-skeleton ${className}`.trim()} aria-hidden="true" />;
}
