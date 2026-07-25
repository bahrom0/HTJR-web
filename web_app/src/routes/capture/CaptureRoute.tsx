import { useEffect, useRef, useState, type DragEvent, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { uploadDocument } from '@features/capture/api';
import { preflightImage } from '@features/capture/preflight';
import { useAccess } from '@shared/access/AccessProvider';
import {
  listPendingUploads,
  removePendingUpload,
  savePendingUpload,
  type PendingUpload,
} from '@shared/upload/outbox';
import { Button, Card, Icon } from '@shared/ui';

type Selection = Readonly<{ file: File; idempotencyKey: string }>;

export default function CaptureRoute() {
  const { csrfToken, reconnect } = useAccess();
  const navigate = useNavigate();
  const cameraInput = useRef<HTMLInputElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingUpload[]>([]);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const firstPending = pending[0];

  useEffect(() => {
    void listPendingUploads()
      .then(setPending)
      .catch(() => setMessage('Локальное восстановление загрузки недоступно в этом браузере.'));
  }, []);
  useEffect(() => {
    if (!selection) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(selection.file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [selection]);

  async function choose(file: File | undefined) {
    if (!file) return;
    setMessage(null);
    const error = await preflightImage(file);
    if (error) {
      setSelection(null);
      setMessage(error);
      return;
    }
    setSelection({ file, idempotencyKey: crypto.randomUUID() });
  }

  async function send(upload: PendingUpload) {
    if (!csrfToken) {
      setMessage('Сессия обновляется. Повторите загрузку через несколько секунд.');
      await reconnect();
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      await savePendingUpload(upload);
      const response = await uploadDocument(
        upload.file,
        upload.filename,
        upload.idempotencyKey,
        csrfToken,
      );
      if (response.ok) {
        await removePendingUpload(upload.idempotencyKey);
        setPending((items) =>
          items.filter((item) => item.idempotencyKey !== upload.idempotencyKey),
        );
        setSelection(null);
        navigate(`/preparation?pageId=${encodeURIComponent(response.value.pageId)}`, {
          replace: true,
        });
      } else {
        if (!response.error.retryable) await removePendingUpload(upload.idempotencyKey);
        setMessage(response.error.message);
        setPending(await listPendingUploads().catch(() => []));
      }
    } catch {
      setMessage('Не удалось сохранить файл для повтора. Проверьте свободное место браузера.');
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (selection)
      await send({
        idempotencyKey: selection.idempotencyKey,
        file: selection.file,
        filename: selection.file.name,
        mediaType: selection.file.type,
        createdAt: new Date().toISOString(),
      });
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    void choose(event.dataTransfer.files[0]);
  }

  return (
    <main
      className="capture-page"
      id="main-content"
      tabIndex={-1}
      onPaste={(event) => {
        const file = [...event.clipboardData.files][0];
        if (file) void choose(file);
      }}
    >
      <header className="page-heading capture-heading">
        <div>
          <p className="eyebrow">Новый документ</p>
          <h1>Добавьте страницу</h1>
          <p>
            Снимите рукопись камерой или выберите готовое изображение. Оригинал сохранится без
            изменений.
          </p>
        </div>
        <Link className="page-heading__back" to="/">
          <Icon name="arrow" />
          На главную
        </Link>
      </header>
      <div className="capture-layout">
        <form onSubmit={submit} className="capture-workspace">
          <div
            className={`capture-dropzone${dragging ? ' capture-dropzone--active' : ''}`}
            onDragEnter={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
          >
            {preview && selection ? (
              <div className="capture-preview">
                <img src={preview} alt="Предпросмотр выбранной страницы" />
                <div className="capture-preview__meta">
                  <strong>{selection.file.name}</strong>
                  <span>{(selection.file.size / 1024 / 1024).toFixed(1)} МБ</span>
                </div>
              </div>
            ) : (
              <div className="capture-empty">
                <span className="capture-empty__icon">
                  <Icon name="image" />
                </span>
                <h2>Перетащите изображение сюда</h2>
                <p>Также можно вставить его из буфера обмена — Ctrl/⌘ + V.</p>
              </div>
            )}
            <div className="capture-actions">
              <Button type="button" onClick={() => cameraInput.current?.click()}>
                <Icon name="scan" />
                Открыть камеру
              </Button>
              <Button type="button" variant="secondary" onClick={() => fileInput.current?.click()}>
                <Icon name="document" />
                Выбрать файл
              </Button>
            </div>
            <input
              ref={cameraInput}
              className="visually-hidden"
              aria-label="Снять страницу камерой"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              capture="environment"
              onChange={(event) => void choose(event.target.files?.[0])}
            />
            <input
              ref={fileInput}
              className="visually-hidden"
              aria-label="Выбрать изображение"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={(event) => void choose(event.target.files?.[0])}
            />
          </div>
          {message && (
            <p className="capture-message" role="alert">
              {message}
            </p>
          )}
          <div className="capture-submit">
            <p>JPEG, PNG или WebP · до 25 МБ · до 40 Мп</p>
            <Button type="submit" disabled={!selection || busy} isLoading={busy}>
              {busy ? 'Надёжно загружаем…' : 'Создать документ'}
              <Icon name="arrow" />
            </Button>
          </div>
        </form>
        <aside className="capture-aside" aria-label="Подсказки для снимка">
          <Card>
            <p className="eyebrow">Хороший снимок</p>
            <h2>Текст в фокусе, лист целиком</h2>
            <ul>
              <li>держите камеру параллельно странице;</li>
              <li>избегайте теней и бликов;</li>
              <li>оставьте небольшой край вокруг листа.</li>
            </ul>
          </Card>
          {firstPending && (
            <Card className="capture-outbox">
              <p className="eyebrow">Ожидают отправки</p>
              <h2>
                {pending.length} {pending.length === 1 ? 'изображение' : 'изображения'}
              </h2>
              <p>Они сохранены только в этом браузере и не потеряются при кратком сбое сети.</p>
              <Button variant="secondary" disabled={busy} onClick={() => void send(firstPending)}>
                Повторить отправку
              </Button>
            </Card>
          )}
        </aside>
      </div>
    </main>
  );
}
