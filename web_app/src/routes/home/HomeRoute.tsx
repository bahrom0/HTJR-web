import { Link } from 'react-router-dom';
import { motion } from 'motion/react';

import { getDocuments } from '@entities/document';
import { useAccess } from '@shared/access/AccessProvider';
import { motionTransition, useAccessibleMotion } from '@shared/motion';
import { Icon } from '@shared/ui';

export default function HomeRoute() {
  const access = useAccess();
  const canAnimate = useAccessibleMotion();
  const recentDocuments = getDocuments().slice(0, 4);

  return (
    <section className="new-home" aria-labelledby="home-title">
      <motion.div
        className="new-home__hero"
        initial={canAnimate ? { opacity: 0, y: 18 } : false}
        animate={{ opacity: 1, y: 0 }}
        transition={motionTransition.enter}
      >
        <h1 id="home-title">
          <span>Здравствуйте, {access.user?.name || 'пользователь'}</span>
          Готовы распознать новую рукопись?
        </h1>
        <Link className="ui-button ui-button--primary new-home__cta" to="/capture">
          <Icon name="scan" />
          Распознать новую страницу
        </Link>
      </motion.div>

      <section className="new-home__recent" aria-labelledby="recent-title">
        <header>
          <h2 id="recent-title">Недавние документы</h2>
          <Link to="/documents">
            Посмотреть все <Icon name="arrow" />
          </Link>
        </header>

        {recentDocuments.length === 0 ? (
          <div className="new-empty-card">
            <p>Документов пока нет</p>
            <Link className="ui-button ui-button--secondary" to="/capture">
              Добавить первую страницу
            </Link>
          </div>
        ) : (
          <div className="new-home__grid">
            {recentDocuments.map((document, index) => (
              <motion.div
                key={document.id}
                initial={canAnimate ? { opacity: 0, y: 14 } : false}
                animate={{ opacity: 1, y: 0 }}
                transition={{
                  ...motionTransition.enter,
                  delay: canAnimate ? index * 0.04 : 0,
                }}
              >
                <Link className="new-document-tile" to={`/documents/${document.id}`}>
                  <span className="new-document-tile__preview">
                    <Icon name="document" />
                  </span>
                  <span className="new-document-tile__copy">
                    <strong>{document.title}</strong>
                    <span>
                      {new Date(document.updatedAt).toLocaleDateString('ru-RU')}
                      <em>{document.status === 'completed' ? 'Готов' : 'В работе'}</em>
                    </span>
                  </span>
                </Link>
              </motion.div>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}
