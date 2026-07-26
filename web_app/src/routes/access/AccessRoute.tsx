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
import { fadeVariants, motionTransition, useAccessibleMotion } from '@shared/motion';
import { Button, Field, Icon, Status } from '@shared/ui';

function safeReturnTo(value: unknown): string {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')
    ? value
    : '/';
}

function errorText(code: string): string {
  const known: Record<string, string> = {
    account_exists: 'Аккаунт с такой почтой уже существует.',
    email_not_verified: 'Сначала подтвердите почту.',
    access_denied: 'Почта или пароль указаны неверно.',
    invalid_or_expired_code: 'Код неверен или уже истёк.',
    rate_limited: 'Слишком много попыток. Подождите и повторите.',
    network_error: 'Сервер недоступен. Проверьте подключение.',
    request_timeout: 'Сервер отвечает слишком долго. Попробуйте ещё раз.',
  };
  return known[code] ?? 'Не удалось выполнить действие. Проверьте данные и повторите.';
}

type AuthMode = 'sign-in' | 'register' | 'verify' | 'recover';

function modeFromPath(pathname: string): AuthMode {
  if (pathname.endsWith('/register')) return 'register';
  if (pathname.endsWith('/verify')) return 'verify';
  if (pathname.endsWith('/recover')) return 'recover';
  return 'sign-in';
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
  const [accessCode, setAccessCode] = useState('');
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
          eyebrow: 'Вход в аккаунт',
          title: 'Продолжить работу',
          description: 'Ваши документы будут доступны на всех активных сессиях этого аккаунта.',
        },
        register: {
          eyebrow: 'Новый аккаунт',
          title: 'Создать аккаунт',
          description: 'Один аккаунт хранит ваши документы, историю обработки и настройки.',
        },
        verify: {
          eyebrow: 'Подтверждение почты',
          title: 'Введите код из письма',
          description: 'Код действует ограниченное время и после использования становится недействительным.',
        },
        recover: {
          eyebrow: 'Восстановление доступа',
          title: recoveryRequested ? 'Задайте новый пароль' : 'Восстановить пароль',
          description: recoveryRequested
            ? 'Введите одноразовый код и новый пароль.'
            : 'Укажите почту аккаунта. Ответ сервера не раскрывает, зарегистрирована ли она.',
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
    setNotice(undefined);
    navigate('/access', {
      replace: true,
      state: { email, returnTo },
    });
  }

  async function resend() {
    if (resendRemaining > 0) return;
    if (!email) {
      setError('Сначала укажите почту.');
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
    setCode('');
    setNewPassword('');
    setDevelopmentCode(undefined);
    setNotice(undefined);
    setRecoveryRequested(false);
    navigate('/access', { replace: true, state: { email, returnTo } });
  }

  async function legacySignIn(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(undefined);
    const message = await access.exchange(accessCode);
    setSubmitting(false);
    if (message) {
      setError(
        message === 'The access code or session is invalid.'
          ? 'Код недействителен, истёк или уже использован.'
          : 'Не удалось войти по временному коду.',
      );
      return;
    }
    navigate(returnTo, { replace: true });
  }

  return (
    <section className="access-page" aria-labelledby="access-title">
      <motion.div
        className="access-panel"
        initial={canAnimate ? 'hidden' : false}
        animate="visible"
        variants={fadeVariants}
        transition={motionTransition.enter}
      >
        <div className="access-story">
          <div className="access-story__mark">
            <Icon name="shield" />
          </div>
          <p className="eyebrow">Tajik HTR Studio</p>
          <h1 id="access-title">Рукописи остаются вашими — между входами и устройствами.</h1>
          <p>
            Аккаунт связывает документы, распознавание и исправления с вами, а не с временным
            кодом браузера.
          </p>
          <ul className="access-benefits">
            <li>
              <Icon name="shield" />
              Пароли защищены Argon2id
            </li>
            <li>
              <Icon name="clock" />
              Сессии можно увидеть и отозвать
            </li>
            <li>
              <Icon name="document" />
              Документы изолированы по аккаунтам
            </li>
          </ul>
        </div>

        <div className="access-form-card">
          <p className="eyebrow">{copy.eyebrow}</p>
          <h2>{copy.title}</h2>
          <p>{copy.description}</p>

          {mode === 'sign-in' ? (
            <form className="access-form" onSubmit={signIn}>
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
                <Icon name="arrow" />
              </Button>
            </form>
          ) : null}

          {mode === 'register' ? (
            <form className="access-form" onSubmit={register}>
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
                <Icon name="arrow" />
              </Button>
            </form>
          ) : null}

          {mode === 'verify' ? (
            <form className="access-form" onSubmit={verify}>
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
                <Icon name="arrow" />
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
            <form className="access-form" onSubmit={recover}>
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
                <Icon name="arrow" />
              </Button>
            </form>
          ) : null}

          {notice ? <Status tone="info">{notice}</Status> : null}
          {developmentCode ? (
            <Status tone="info">
              Локальный код разработки: <strong>{developmentCode}</strong>
            </Status>
          ) : null}

          <nav className="access-links" aria-label="Действия с аккаунтом">
            {mode !== 'sign-in' ? <Link to="/access">Уже есть аккаунт</Link> : null}
            {mode === 'sign-in' ? <Link to="/access/register">Создать аккаунт</Link> : null}
            {mode === 'sign-in' ? <Link to="/access/recover">Забыли пароль?</Link> : null}
          </nav>

          {mode === 'sign-in' ? (
            <details className="access-legacy">
              <summary>Временный код администратора</summary>
              <form className="access-form" onSubmit={legacySignIn}>
                <Field
                  label="Код доступа"
                  hint="Доступно только если сервер запущен с dev/admin-флагом."
                  value={accessCode}
                  onChange={(event) => setAccessCode(event.target.value.toUpperCase())}
                  spellCheck={false}
                  required
                />
                <Button type="submit" variant="secondary" isLoading={submitting}>
                  Войти по коду
                </Button>
              </form>
            </details>
          ) : null}
        </div>
      </motion.div>
    </section>
  );
}
