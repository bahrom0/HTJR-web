import { useState, type FormEvent } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { motion } from 'motion/react';

import { useAccess } from '@shared/access/AccessProvider';
import { fadeVariants, motionTransition, useAccessibleMotion } from '@shared/motion';
import { Button, Field, Icon, Status } from '@shared/ui';

function safeReturnTo(value: unknown): string {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') ? value : '/';
}

export default function AccessRoute() {
  const access = useAccess();
  const location = useLocation();
  const navigate = useNavigate();
  const canAnimate = useAccessibleMotion();
  const [code, setCode] = useState('');
  const [error, setError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);
  const returnTo = safeReturnTo((location.state as { returnTo?: unknown } | null)?.returnTo);
  if (access.state === 'authenticated') return <Navigate to={returnTo} replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true); setError(undefined);
    const message = await access.exchange(code);
    setSubmitting(false);
    if (message) setError(message === 'The access code or session is invalid.' ? 'Код недействителен, истёк или уже использован.' : 'Сервер не ответил. Проверьте подключение и попробуйте снова.');
    else navigate(returnTo, { replace: true });
  }

  return (
    <section className="access-page" aria-labelledby="access-title">
      <motion.div className="access-panel" initial={canAnimate ? 'hidden' : false} animate="visible" variants={fadeVariants} transition={motionTransition.enter}>
        <div className="access-story">
          <div className="access-story__mark"><Icon name="shield" /></div>
          <p className="eyebrow">Tajik HTR Studio</p>
          <h1 id="access-title">Спокойное рабочее пространство для ваших рукописей.</h1>
          <p>Браузер подключается к вашему локальному серверу. Изображения, тексты и исправления остаются под вашим контролем.</p>
          <div className="access-connection" aria-label="Схема подключения"><span>Браузер</span><i /><Icon name="shield" /><i /><span>Ваш сервер</span></div>
          <ul className="access-benefits"><li><Icon name="shield" />HttpOnly-сессия</li><li><Icon name="clock" />Одноразовый код на 15 минут</li><li><Icon name="document" />Раздельные версии текста</li></ul>
        </div>
        <div className="access-form-card">
          <p className="eyebrow">Защищённое подключение</p><h2>Введите временный код</h2><p>Создайте код в терминале сервера. После входа вы вернётесь на открытый ранее экран.</p>
          <form className="access-form" onSubmit={submit}>
            <Field label="Код доступа" hint="Формат: XXXX-XXXX-XXXX" name="access-code" value={code} onChange={(event) => setCode(event.target.value.toUpperCase())} error={error} autoComplete="one-time-code" spellCheck={false} inputMode="text" required />
            <Button type="submit" isLoading={submitting} aria-label="Подключиться к серверу">{submitting ? 'Подключаемся…' : 'Подключиться к серверу'}<Icon name="arrow" /></Button>
          </form>
          {error ? <Button variant="quiet" onClick={() => void access.reconnect()}>Проверить соединение</Button> : null}
          <Status tone="info">Код и токен сессии не сохраняются в локальном хранилище браузера.</Status>
        </div>
      </motion.div>
    </section>
  );
}
