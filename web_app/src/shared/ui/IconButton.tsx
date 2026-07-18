import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  children: ReactNode;
};

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, children, className = '', type = 'button', ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={`ui-icon-button ${className}`.trim()}
      aria-label={label}
      {...props}
    >
      {children}
    </button>
  );
});
