import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import {
  type JobStreamState,
  createJobSubscription,
  projectJobProgress,
} from '@features/job-progress';
import { getRecognitionResult, type RecognitionResult } from '@features/results/api';
import { Button, Card, Icon, Status } from '@shared/ui';

function downloadText(text: string) {
  const file = new Blob([text], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'распознанный-текст.txt';
  link.click();
  URL.revokeObjectURL(url);
}

export default function ResultRoute() {
  const [params] = useSearchParams();
  const jobId = params.get('jobId');
  const [stream, setStream] = useState<JobStreamState | null>(null);
  const [result, setResult] = useState<RecognitionResult | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const progress = stream?.snapshot ? projectJobProgress(stream.snapshot) : null;

  async function copyResult(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setMessage('Текст скопирован в буфер обмена.');
    } catch {
      setMessage('Не удалось скопировать текст. Выделите его в поле и скопируйте вручную.');
    }
  }

  useEffect(() => {
    if (!jobId) return;
    const subscription = createJobSubscription({ jobId, onState: setStream });
    void subscription.start();
    return () => subscription.dispose();
  }, [jobId]);

  useEffect(() => {
    if (
      !jobId ||
      !progress?.isTerminal ||
      !['completed', 'partial'].includes(stream?.snapshot?.state ?? '')
    ) {
      return;
    }
    void getRecognitionResult(jobId).then((response) => {
      if (response.ok) setResult(response.value);
      else setMessage(response.error.message);
    });
  }, [jobId, progress?.isTerminal, stream?.snapshot?.state]);

  if (!jobId) {
    return (
      <main className="result-page" id="main-content" tabIndex={-1}>
        <Card>
          <h1>Не выбрана задача распознавания</h1>
          <p>Откройте этот экран после подтверждения областей CRAFT.</p>
          <Link className="ui-button ui-button--primary" to="/capture">
            Распознать страницу
          </Link>
        </Card>
      </main>
    );
  }

  const retryableFailure = stream?.snapshot?.state === 'failed_retryable';
  const regionLink = stream?.snapshot
    ? `/regions?pageId=${encodeURIComponent(stream.snapshot.pageId)}&jobId=${encodeURIComponent(jobId)}`
    : '/regions';

  return (
    <main className="result-page" id="main-content" tabIndex={-1}>
      <header className="page-heading result-heading">
        <div>
          <p className="eyebrow">Распознавание страницы</p>
          <h1>{result ? 'Текст готов к проверке' : 'Распознаём подтверждённые строки'}</h1>
          <p>
            {result
              ? 'Это исходный результат модели. Он сохранён отдельно от будущих правок.'
              : 'Можно оставить страницу: ход работы сохранён на сервере и восстановится при возвращении.'}
          </p>
        </div>
        <Link className="page-heading__back" to={regionLink}>
          К областям
        </Link>
      </header>

      {!result ? (
        <Card className="result-progress" aria-live="polite">
          <Status tone={retryableFailure ? 'warning' : 'info'}>
            {progress?.stageLabel ?? 'Подключаемся к задаче…'}
          </Status>
          <h2>{progress?.counterLabel ?? 'Сервер сообщает реальный этап работы'}</h2>
          <p>
            {retryableFailure
              ? 'Распознавание прервалось. Вернитесь к областям, чтобы безопасно повторить задачу.'
              : 'Текст появится здесь автоматически после окончания обработки.'}
          </p>
          {message ? <p role="alert">{message}</p> : null}
          <div className="result-actions">
            <Link className="ui-button ui-button--secondary" to={regionLink}>
              Вернуться к областям
            </Link>
            <Link className="ui-button ui-button--quiet" to="/capture">
              Новая страница
            </Link>
          </div>
        </Card>
      ) : (
        <section className="result-layout" aria-label="Распознанный текст и действия">
          <Card className="result-text-card">
            <div className="result-card-heading">
              <div>
                <p className="eyebrow">Исходный текст</p>
                <h2>
                  {result.isPartial ? 'Есть строки, требующие внимания' : 'Все строки обработаны'}
                </h2>
              </div>
              <Status tone={result.isPartial ? 'warning' : 'success'}>
                {result.isPartial ? 'Частичный результат' : 'Готово'}
              </Status>
            </div>
            <textarea aria-label="Распознанный текст" value={result.rawText} readOnly />
          </Card>
          <aside className="result-sidebar">
            <Card>
              <p className="eyebrow">Следующий шаг</p>
              <h2>Проверьте и отредактируйте текст</h2>
              <p>
                Перейдите в интерактивный редактор для проверки строк и автокоррекции букв.
              </p>
              <Link className="ui-button ui-button--primary" to={`/editor?jobId=${encodeURIComponent(jobId)}`}>
                <Icon name="sparkles" /> Открыть в редакторе
              </Link>
            </Card>
            <Card>
              <p className="eyebrow">Быстрые действия</p>
              <div className="result-actions">
                <Button variant="secondary" onClick={() => void copyResult(result.rawText)}>
                  Копировать текст
                </Button>
                <Button variant="secondary" onClick={() => downloadText(result.rawText)}>
                  Скачать TXT
                </Button>
                <Link className="ui-button ui-button--quiet" to="/capture">
                  Распознать новую страницу
                </Link>
              </div>
              {message ? <p role="status">{message}</p> : null}
            </Card>
          </aside>
        </section>
      )}
    </main>
  );
}
