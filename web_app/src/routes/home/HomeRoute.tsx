import { Link } from 'react-router-dom';
import { motion } from 'motion/react';

import { useAccess } from '@shared/access/AccessProvider';
import { useNetworkStatus } from '@shared/lib/useNetworkStatus';
import { fadeVariants, motionTransition, useAccessibleMotion } from '@shared/motion';
import { Badge, Card, Icon, Status } from '@shared/ui';

const workflow = [
  ['01', 'Источник', 'Добавьте фотографию страницы', 'image'],
  ['02', 'Подготовка', 'Выровняйте и проверьте качество', 'sparkles'],
  ['03', 'Распознавание', 'Получите реальные регионы и текст', 'scan'],
  ['04', 'Проверка', 'Подтвердите итоговую версию', 'shield'],
] as const;

function formatExpiry(value: string | null): string {
  if (!value) return 'срок уточняется';
  return new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}

export default function HomeRoute() {
  const canAnimate = useAccessibleMotion();
  const access = useAccess();
  const isOnline = useNetworkStatus();
  return (
    <section className="home-page" aria-labelledby="home-title">
      <motion.div className="home-hero" initial={canAnimate ? 'hidden' : false} animate="visible" variants={fadeVariants} transition={motionTransition.enter}>
        <div className="home-hero__copy">
          <Badge tone="success">Локальная мастерская подключена</Badge>
          <p className="eyebrow">Тихая работа с рукописями</p>
          <h1 id="home-title">Превратите снимок страницы в проверенный документ.</h1>
          <p className="home-hero__lead">Оригинал остаётся неизменным, каждый этап сохраняется отдельно, а результат всегда можно проверить вручную.</p>
          <div className="home-hero__actions">
            <Link className="ui-button ui-button--primary" to="/capture"><Icon name="scan" />Начать с изображения</Link>
            <Link className="ui-button ui-button--secondary" to="/documents"><Icon name="document" />Открыть документы</Link>
          </div>
        </div>
        <aside className="session-card" aria-label="Состояние подключения">
          <div className="session-card__visual" aria-hidden="true"><Icon name="shield" /><span /><Icon name="document" /></div>
          <p className="eyebrow">Состояние системы</p>
          <h2>{isOnline ? 'Сервер на связи' : 'Работа без сети'}</h2>
          <Status tone={isOnline ? 'success' : 'warning'}>{isOnline ? 'Сервер отвечает через защищённую сессию' : 'Серверные действия временно недоступны'}</Status>
          <dl className="session-card__facts">
            <div><dt>Доступ</dt><dd>{access.state === 'authenticated' ? 'Разрешён' : 'Проверяется'}</dd></div>
            <div><dt>Сессия до</dt><dd>{formatExpiry(access.expiresAt)}</dd></div>
            <div><dt>Хранение</dt><dd>На вашем сервере</dd></div>
          </dl>
        </aside>
      </motion.div>

      <section className="home-section" aria-labelledby="workflow-title">
        <div className="section-heading"><div><p className="eyebrow">Путь документа</p><h2 id="workflow-title">Четыре понятных этапа</h2></div><p>Никаких скрытых изменений: подготовка, распознавание и исправления сохраняются раздельно.</p></div>
        <div className="workflow-grid">
          {workflow.map(([number, title, description, icon], index) => (
            <motion.article key={number} className="workflow-card" initial={canAnimate ? { opacity: 0, y: 12 } : false} animate={{ opacity: 1, y: 0 }} transition={{ ...motionTransition.enter, delay: canAnimate ? index * 0.04 : 0 }}>
              <div className="workflow-card__top"><span>{number}</span><Icon name={icon} /></div><h3>{title}</h3><p>{description}</p>
            </motion.article>
          ))}
        </div>
      </section>

      <section className="home-lower-grid">
        <Card className="documents-empty">
          <div className="soft-icon"><Icon name="document" /></div><p className="eyebrow">Последние документы</p><h2>Здесь появится ваша работа</h2><p>Документы появятся после первой безопасной загрузки. Мы не подставляем демонстрационные записи.</p><Link to="/capture">Подготовиться к загрузке <Icon name="arrow" /></Link>
        </Card>
        <Card className="privacy-card">
          <div className="soft-icon"><Icon name="shield" /></div><p className="eyebrow">Приватность по умолчанию</p><h2>Изображения не покидают ваш сервер</h2><p>Код доступа одноразовый, токен недоступен странице, а каждый объект привязан к своей сессии.</p><Link to="/settings">Настройки и приватность <Icon name="arrow" /></Link>
        </Card>
      </section>
    </section>
  );
}
