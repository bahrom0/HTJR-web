import { useId, type InputHTMLAttributes } from 'react';

type FieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  error?: string;
  hint?: string;
};

export function Field({ label, error, hint, id: suppliedId, ...props }: FieldProps) {
  const generatedId = useId();
  const id = suppliedId ?? generatedId;
  const descriptionId = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <label className="ui-field" htmlFor={id}>
      <span className="ui-field__label">{label}</span>
      <input id={id} aria-invalid={Boolean(error)} aria-describedby={descriptionId} {...props} />
      {error ? (
        <span id={`${id}-error`} className="ui-field__error" role="alert">
          {error}
        </span>
      ) : null}
      {!error && hint ? (
        <span id={`${id}-hint`} className="ui-field__hint">
          {hint}
        </span>
      ) : null}
    </label>
  );
}
