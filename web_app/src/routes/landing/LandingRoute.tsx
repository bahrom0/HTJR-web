import { Link } from 'react-router-dom';

import { ProjectHeader } from '@app/shell/ProjectHeader';
import { Icon } from '@shared/ui';

export default function LandingRoute() {
  return (
    <section className="landing" aria-labelledby="landing-title">
      <div className="landing__frame">
        <ProjectHeader variant="landing" />

        <div className="landing__hero">
          <div className="landing__copy">
            <p className="landing__eyebrow">Распознавание таджикского текста</p>
            <h1 id="landing-title">Рукописи становятся редактируемым текстом.</h1>
            <p className="landing__description">
              TJOCR помогает загрузить страницу, проверить найденные строки, распознать таджикский
              текст и подготовить аккуратный документ.
            </p>
            <Link className="landing__cta" to="/app">
              Запустить приложение
              <Icon name="arrow" />
            </Link>
            <p className="landing__note">Результат остаётся под вашим контролем на каждом этапе.</p>
          </div>

          <figure className="landing__visual">
            <img src="/auth-hero-v2.png" alt="Монохромный горный пейзаж" />
            <figcaption>
              <span>От изображения</span>
              <strong>к проверенному документу</strong>
            </figcaption>
          </figure>
        </div>

        <section className="landing__workflow" aria-labelledby="landing-workflow-title">
          <div className="landing__workflow-heading">
            <div>
              <p>Простой процесс</p>
              <h2 id="landing-workflow-title">Три шага до готового текста</h2>
            </div>
            <p className="landing__workflow-description">
              Каждый этап остаётся понятным: от исходного изображения до проверенного документа.
            </p>
          </div>
          <ol>
            <li>
              <span>01</span>
              <strong>Загрузите страницу</strong>
              <p>Используйте фотографию или готовое изображение документа.</p>
            </li>
            <li>
              <span>02</span>
              <strong>Проверьте строки</strong>
              <p>Уточните области и порядок чтения до распознавания.</p>
            </li>
            <li>
              <span>03</span>
              <strong>Доведите текст</strong>
              <p>Сверьте результат, внесите правки и подготовьте экспорт.</p>
            </li>
          </ol>
        </section>

        <footer className="landing__footer">
          <span>TJOCR</span>
          <p>Таджикские рукописи — в понятном цифровом процессе.</p>
        </footer>
      </div>
    </section>
  );
}
