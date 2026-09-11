import { useMemo, useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { motion } from 'motion/react';

import { useAccess } from '@shared/access/AccessProvider';
import { motionTransition, useAccessibleMotion } from '@shared/motion';
import { Button, Field } from '@shared/ui';

type AuthMode = 'sign-in' | 'register';

function safeReturnTo(value: unknown): string {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')
    ? value
    : '/app';
}

function modeFromPath(pathname: string): AuthMode {
  return pathname.endsWith('/register') ? 'register' : 'sign-in';
}

function errorText(code: string): string {
  const known: Record<string, string> = {
    account_exists: 'Аккаунт с такой почтой уже существует.',
    access_denied: 'Почта или пароль указаны неверно.',
    invalid_account: 'Проверьте имя, почту и пароль.',
    rate_limited: 'Слишком много попыток. Подождите и повторите.',
    network_error: 'Сервер недоступен. Проверьте подключение.',
    request_timeout: 'Сервер отвечает слишком долго. Попробуйте ещё раз.',
  };
  return known[code] ?? 'Не удалось выполнить действие. Проверьте данные и повторите.';
}

export default function AccessRoute() {
  const access = useAccess();
  const location = useLocation();
  const navigate = useNavigate();
  const canAnimate = useAccessibleMotion();
  const mode = modeFromPath(location.pathname);
  const routeState = location.state as { returnTo?: unknown; email?: unknown } | null;
  const returnTo = safeReturnTo(routeState?.returnTo);
  const [email, setEmail] = useState(typeof routeState?.email === 'string' ? routeState.email : '');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);

  const copy = useMemo(
    () =>
      mode === 'register'
        ? {
            title: 'Создать аккаунт',
            description: 'Документы и результаты будут привязаны к вашему аккаунту.',
          }
        : {
            title: '\u0412\u0445\u043e\u0434 \u0432 TJOCR',
            description:
              '\u041f\u043b\u0430\u0442\u0444\u043e\u0440\u043c\u0430 \u0434\u043b\u044f \u0440\u0430\u0441\u043f\u043e\u0437\u043d\u0430\u0432\u0430\u043d\u0438\u044f \u0442\u0430\u0434\u0436\u0438\u043a\u0441\u043a\u043e\u0433\u043e \u0442\u0435\u043a\u0441\u0442\u0430.',
          },
    [mode],
  );

  if (access.state === 'authenticated') return <Navigate to={returnTo} replace />;

  async function signIn(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(undefined);
    const result = await access.login(email, password);
    setSubmitting(false);
    if (!result) {
      navigate(returnTo, { replace: true });
      return;
    }
    setError(errorText(result.split(':', 1)[0] ?? 'unknown_error'));
  }

  async function register(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(undefined);
    const result = await access.register(email, name, password);
    setSubmitting(false);
    if (!result) {
      navigate(returnTo, { replace: true });
      return;
    }
    setError(errorText(result.split(':', 1)[0] ?? 'unknown_error'));
  }

  return (
    <section className="new-auth" aria-labelledby="access-title">
      <div className="new-auth__shell">
        <motion.aside
          className="new-auth__visual"
          aria-hidden="true"
          initial={canAnimate ? { opacity: 0, x: -18, scale: 1.015 } : false}
          animate={{ opacity: 1, x: 0, scale: 1 }}
          transition={motionTransition.enter}
        >
          <img src="/auth-hero-v2.png" alt="" />
          <span className="new-auth__visual-wash" />
        </motion.aside>
        <motion.div
          className="new-auth__card"
          initial={canAnimate ? { opacity: 0, y: 18, scale: 0.985 } : false}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={motionTransition.enter}
        >
          <div className="new-auth__brand-logo">
            <img
              className="new-auth__brand-logo-light"
              src="/tjocr-logo-auth-light.png"
              alt="TJOCR"
            />
            <img className="new-auth__brand-logo-dark" src="/tjocr-logo-auth-dark.png" alt="" />
          </div>
          <h1 id="access-title">
            {copy.title.split('\n').map((line) => (
              <span key={line}>{line}</span>
            ))}
          </h1>
          <p className="new-auth__description">{copy.description}</p>

          {mode === 'sign-in' ? (
            <form className="new-auth__form" onSubmit={signIn}>
              <Field
                label="Электронная почта"
                type="email"
                autoComplete="email"
                placeholder="email@example.com"
                className="new-auth__input"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
              <Field
                label="Пароль"
                type="password"
                autoComplete="current-password"
                placeholder="Пароль"
                className="new-auth__input"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                error={error}
                required
              />
              <Button type="submit" isLoading={submitting}>
                Войти
              </Button>
            </form>
          ) : (
            <form className="new-auth__form" onSubmit={register}>
              <Field
                label="Ваше имя"
                autoComplete="name"
                placeholder="Ваше имя"
                className="new-auth__input"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
              <Field
                label="Электронная почта"
                type="email"
                autoComplete="email"
                placeholder="email@example.com"
                className="new-auth__input"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
              <Field
                label="Пароль"
                type="password"
                autoComplete="new-password"
                placeholder="Пароль"
                className="new-auth__input"
                minLength={12}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                hint="Не менее 12 символов."
                error={error}
                required
              />
              <Button type="submit" isLoading={submitting}>
                Создать аккаунт
              </Button>
            </form>
          )}

          <nav className="new-auth__links" aria-label="Действия с аккаунтом">
            {mode === 'sign-in' ? (
              <Link to="/access/register">Создать аккаунт</Link>
            ) : (
              <Link to="/access">Уже есть аккаунт</Link>
            )}
          </nav>
        </motion.div>
      </div>
    </section>
  );
}
