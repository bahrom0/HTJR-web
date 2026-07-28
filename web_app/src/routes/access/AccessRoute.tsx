import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { motion } from 'motion/react';

import { useAccess } from '@shared/access/AccessProvider';
import {
  confirmPasswordRecovery,
  registerAccount,
  requestPasswordRecovery,
  resendAccountVerification,
  verifyAccountEmail,
} from '@shared/api/client';
import { motionTransition, useAccessibleMotion } from '@shared/motion';
import { Button, Field, Status } from '@shared/ui';

type AuthMode = 'sign-in' | 'register' | 'verify' | 'recover';

function safeReturnTo(value: unknown): string {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')
    ? value
    : '/';
}

function modeFromPath(pathname: string): AuthMode {
  if (pathname.endsWith('/register')) return 'register';
  if (pathname.endsWith('/verify')) return 'verify';
  if (pathname.endsWith('/recover')) return 'recover';
  return 'sign-in';
}

function errorText(code: string): string {
  const known: Record<string, string> = {
    account_exists: 'Аккаунт с такой почтой уже существует.',
    email_not_verified: 'Сначала подтвердите электронную почту.',
    access_denied: 'Почта или пароль указаны неверно.',
    invalid_or_expired_code: 'Код неверен или уже истёк.',
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
  const routeState = location.state as {
    returnTo?: unknown;
    email?: unknown;
    developmentCode?: unknown;
    resendAfter?: unknown;
  } | null;
  const returnTo = safeReturnTo(routeState?.returnTo);

  const [email, setEmail] = useState(
    typeof routeState?.email === 'string' ? routeState.email : '',
  );
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [developmentCode, setDevelopmentCode] = useState<string | undefined>(
    typeof routeState?.developmentCode === 'string' ? routeState.developmentCode : undefined,
  );
  const [resendRemaining, setResendRemaining] = useState(() => {
    if (typeof routeState?.resendAfter !== 'number') return 0;
    return Math.max(0, Math.ceil((routeState.resendAfter - Date.now()) / 1000));
  });
  const [submitting, setSubmitting] = useState(false);
  const [recoveryRequested, setRecoveryRequested] = useState(false);

  useEffect(() => {
    if (resendRemaining <= 0) return;
    const timer = window.setInterval(
      () => setResendRemaining((current) => Math.max(0, current - 1)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [resendRemaining]);

  const copy = useMemo(
    () =>
      ({
        'sign-in': {
          title: 'Tajik HTR\nStudio',
          description: 'Войдите, чтобы продолжить работу с рукописями.',
        },
        register: {
          title: 'Создать аккаунт',
          description: 'Документы и результаты будут привязаны к вашему аккаунту.',
        },
        verify: {
          title: 'Подтвердить почту',
          description: 'Введите шестизначный код из письма.',
        },
        recover: {
          title: recoveryRequested ? 'Новый пароль' : 'Восстановить пароль',
          description: recoveryRequested
            ? 'Введите код восстановления и новый пароль.'
            : 'Укажите почту аккаунта, чтобы получить код.',
        },
      })[mode],
    [mode, recoveryRequested],
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
    const errorCode = result.split(':', 1)[0] ?? 'unknown_error';
    if (errorCode === 'email_not_verified') {
      navigate('/access/verify', { state: { email, returnTo } });
      return;
    }
    setError(errorText(errorCode));
  }

  async function register(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(undefined);
    const result = await registerAccount(email, name, password);
    setSubmitting(false);
    if (!result.ok) {
      setError(errorText(result.error.code));
      return;
    }
    navigate('/access/verify', {
      state: {
        email: result.value.email,
        returnTo,
        developmentCode: result.value.developmentCode,
        resendAfter: Date.now() + 60_000,
      },
    });
  }

  async function verify(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(undefined);
    const result = await verifyAccountEmail(email, code);
    setSubmitting(false);
    if (!result.ok) {
      setError(errorText(result.error.code));
      return;
    }
    setCode('');
    setDevelopmentCode(undefined);
    navigate('/access', { replace: true, state: { email, returnTo } });
  }

  async function resend() {
    if (resendRemaining > 0) return;
    if (!email) {
      setError('Сначала укажите электронную почту.');
      return;
    }
    setSubmitting(true);
    setError(undefined);
    const result = await resendAccountVerification(email);
    setSubmitting(false);
    if (!result.ok) {
      setError(errorText(result.error.code));
      return;
    }
    setDevelopmentCode(result.value.developmentCode);
    setResendRemaining(60);
    setNotice('Новый код создан. Проверьте почту.');
  }

  async function recover(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(undefined);
    if (!recoveryRequested) {
      const result = await requestPasswordRecovery(email);
      setSubmitting(false);
      if (!result.ok) {
        setError(errorText(result.error.code));
        return;
      }
      setDevelopmentCode(result.value.developmentCode);
      setRecoveryRequested(true);
      setNotice('Если аккаунт существует, код восстановления создан.');
      return;
    }
    const result = await confirmPasswordRecovery(email, code, newPassword);
    setSubmitting(false);
    if (!result.ok) {
      setError(errorText(result.error.code));
      return;
    }
    setDevelopmentCode(undefined);
    navigate('/access', { replace: true, state: { email, returnTo } });
  }

  return (
    <section className="new-auth" aria-labelledby="access-title">
      <motion.div
        className="new-auth__card"
        initial={canAnimate ? { opacity: 0, y: 18, scale: 0.985 } : false}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={motionTransition.enter}
      >
        <p className="new-auth__brand">Tajik HTR Studio</p>
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
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
            <Field
              label="Пароль"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              error={error}
              required
            />
            <Button type="submit" isLoading={submitting}>
              Войти
            </Button>
          </form>
        ) : null}

        {mode === 'register' ? (
          <form className="new-auth__form" onSubmit={register}>
            <Field
              label="Ваше имя"
              autoComplete="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
            <Field
              label="Электронная почта"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
            <Field
              label="Пароль"
              type="password"
              autoComplete="new-password"
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
        ) : null}

        {mode === 'verify' ? (
          <form className="new-auth__form" onSubmit={verify}>
            <Field
              label="Электронная почта"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
            <Field
              label="Код подтверждения"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
              error={error}
              required
            />
            <Button type="submit" isLoading={submitting}>
              Подтвердить почту
            </Button>
            <Button
              variant="quiet"
              onClick={() => void resend()}
              disabled={submitting || resendRemaining > 0}
            >
              {resendRemaining > 0
                ? `Новый код через ${resendRemaining} с`
                : 'Отправить новый код'}
            </Button>
          </form>
        ) : null}

        {mode === 'recover' ? (
          <form className="new-auth__form" onSubmit={recover}>
            <Field
              label="Электронная почта"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              readOnly={recoveryRequested}
              required
            />
            {recoveryRequested ? (
              <>
                <Field
                  label="Код восстановления"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={code}
                  onChange={(event) =>
                    setCode(event.target.value.replace(/\D/g, '').slice(0, 6))
                  }
                  required
                />
                <Field
                  label="Новый пароль"
                  type="password"
                  autoComplete="new-password"
                  minLength={12}
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                  error={error}
                  required
                />
              </>
            ) : null}
            <Button type="submit" isLoading={submitting}>
              {recoveryRequested ? 'Сохранить новый пароль' : 'Получить код'}
            </Button>
          </form>
        ) : null}

        {notice ? <Status tone="info">{notice}</Status> : null}
        {developmentCode ? (
          <Status tone="info">
            Локальный код разработки: <strong>{developmentCode}</strong>
          </Status>
        ) : null}

        <nav className="new-auth__links" aria-label="Действия с аккаунтом">
          {mode !== 'sign-in' ? <Link to="/access">Уже есть аккаунт</Link> : null}
          {mode === 'sign-in' ? <Link to="/access/register">Создать аккаунт</Link> : null}
          {mode === 'sign-in' ? <Link to="/access/recover">Забыли пароль?</Link> : null}
        </nav>
      </motion.div>
    </section>
  );
}
