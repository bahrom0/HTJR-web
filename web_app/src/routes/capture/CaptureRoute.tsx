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
      .catch(() =>
        setMessage('Локальное восстановление загрузки недоступно в этом браузере.'),
      );
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
      setMessage(
        'Не удалось сохранить файл для повтора. Проверьте свободное место браузера.',
      );
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!selection) return;
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
      className="new-capture"
      id="main-content"
      tabIndex={-1}
      onPaste={(event) => {
        const file = [...event.clipboardData.files][0];
        if (file) void choose(file);
      }}
    >
      <h1>Новый документ</h1>

      <form onSubmit={submit} className="new-capture__form">
        <div
          className={`new-capture__dropzone ${dragging ? 'is-dragging' : ''}`}
          onDragEnter={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          {preview && selection ? (
            <div className="new-capture__selected">
              <img src={preview} alt="Предпросмотр выбранной страницы" />
              <span className="new-capture__file-icon">
                <Icon name="image" />
              </span>
              <strong>{selection.file.name}</strong>
              <p>{(selection.file.size / 1024 / 1024).toFixed(2)} МБ</p>
              <Button type="button" variant="secondary" onClick={() => setSelection(null)}>
                Заменить изображение
              </Button>
            </div>
          ) : (
            <div className="new-capture__empty">
              <span className="new-capture__file-icon">
                <Icon name="image" />
              </span>
              <strong>Перетащите изображение сюда</strong>
              <p>или выберите файл с устройства</p>
              <Button
                type="button"
                variant="secondary"
                onClick={() => fileInput.current?.click()}
              >
                Выбрать файл
              </Button>
              <Button type="button" variant="quiet" onClick={() => cameraInput.current?.click()}>
                Снять камерой
              </Button>
            </div>
          )}
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

        {message ? (
          <p className="new-capture__message" role="alert">
            {message}
          </p>
        ) : null}

        <div className="new-capture__actions">
          <Link className="ui-button ui-button--secondary" to="/">
            Отмена
          </Link>
          <Button type="submit" disabled={!selection || busy} isLoading={busy}>
            {busy ? 'Загружаем…' : 'Продолжить'}
          </Button>
        </div>
      </form>

      {firstPending ? (
        <Card className="new-capture__outbox">
          <p>{pending.length} файл(а) ожидают отправки</p>
          <Button variant="secondary" disabled={busy} onClick={() => void send(firstPending)}>
            Повторить
          </Button>
        </Card>
      ) : null}
    </main>
  );
}
