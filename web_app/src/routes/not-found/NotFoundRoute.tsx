import { Link } from 'react-router-dom';

export default function NotFoundRoute() {
  return (
    <section aria-labelledby="not-found-title" className="semantic-card">
      <h1 id="not-found-title">Страница не найдена</h1>
      <p>Этот маршрут пока не входит в реализованные сессии.</p>
      <Link to="/">Вернуться на главную</Link>
    </section>
  );
}
