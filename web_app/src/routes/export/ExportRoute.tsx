import { useCallback, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { getDocumentById } from '@entities/document';
import { loadEditorState } from '@features/editor';
import { Badge, Button, Card, Icon, Status } from '@shared/ui';

interface ExportSuccessState {
  type: 'download' | 'copy' | 'share';
  fileName: string;
  fileSize: string;
  timestamp: string;
}

export default function ExportRoute() {
  const [searchParams] = useSearchParams();
  const documentId = searchParams.get('documentId');
  const jobId = searchParams.get('jobId');
  const docOrJobId = documentId || jobId || undefined;

  // Load document & editor blocks state
  const doc = useMemo(() => {
    if (documentId) {
      return getDocumentById(documentId);
    }
    if (jobId) {
      return getDocumentById(jobId);
    }
    return undefined;
  }, [documentId, jobId]);

  const blocks = useMemo(() => loadEditorState(docOrJobId), [docOrJobId]);

  const defaultRawText = useMemo(() => {
    if (blocks && blocks.length > 0) {
      return blocks.map((b) => b.editedText).join('\n');
    }
    if (doc && doc.rawText) {
      return doc.rawText;
    }
    return 'Ба номи Худованди бахшандаи меҳрубон\nСаҳифаи 1 аз рукописи 1928 соли\nДастхати таърихии адабиёти классикии тоҷик';
  }, [blocks, doc]);

  const documentTitle = doc?.title || 'Рукопись Tajik HTR';

  // Export options state
  const [preserveLineBreaks, setPreserveLineBreaks] = useState<boolean>(true);
  const [includeTitle, setIncludeTitle] = useState<boolean>(true);
  const [includeMetadata, setIncludeMetadata] = useState<boolean>(true);

  // Status & Notification feedback state
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const [shareStatus, setShareStatus] = useState<string | null>(null);
  const [successState, setSuccessState] = useState<ExportSuccessState | null>(null);

  // Formatted export text computation
  const formattedText = useMemo(() => {
    const parts: string[] = [];

    if (includeTitle) {
      parts.push(`=== ${documentTitle} ===`);
    }

    if (includeMetadata) {
      parts.push(
        `[Дата экспорта: ${new Date().toLocaleDateString('ru-RU')}]\n[Система: Tajik HTR Studio]\n[Документ ID: ${docOrJobId || 'draft-1'}]`,
      );
    }

    let bodyText = defaultRawText;
    if (!preserveLineBreaks) {
      bodyText = bodyText.replace(/\r?\n+/g, ' ');
    }

    parts.push(bodyText);

    return parts.join('\n\n');
  }, [documentTitle, defaultRawText, includeTitle, includeMetadata, preserveLineBreaks, docOrJobId]);

  // Statistics
  const textStats = useMemo(() => {
    const chars = formattedText.length;
    const words = formattedText.trim() ? formattedText.trim().split(/\s+/).length : 0;
    const lines = formattedText.split('\n').length;
    return { chars, words, lines };
  }, [formattedText]);

  // Calculated file size for blob
  const calculateSize = useCallback((text: string) => {
    const bytes = new Blob([text]).size;
    if (bytes < 1024) return `${bytes} Б`;
    return `${(bytes / 1024).toFixed(1)} КБ`;
  }, []);

  const sanitizedFileName = useMemo(() => {
    const base = documentTitle.replace(/[^a-zA-Z0-9а-яА-ЯёЁҷҷҳҳҷҷӯӯӣӣғғ]/g, '_');
    return `${base || 'export_document'}.txt`;
  }, [documentTitle]);

  // Export action handlers
  const handleDownloadTxt = useCallback(() => {
    const blob = new Blob([formattedText], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = sanitizedFileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    setSuccessState({
      type: 'download',
      fileName: sanitizedFileName,
      fileSize: calculateSize(formattedText),
      timestamp: new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }),
    });
  }, [formattedText, sanitizedFileName, calculateSize]);

  const handleCopyToClipboard = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(formattedText);
      setCopyStatus('Скопировано в буфер обмена!');
      setTimeout(() => setCopyStatus(null), 3000);

      setSuccessState({
        type: 'copy',
        fileName: sanitizedFileName,
        fileSize: calculateSize(formattedText),
        timestamp: new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }),
      });
    } catch (err) {
      console.error('Failed to copy text:', err);
      setCopyStatus('Ошибка при копировании');
      setTimeout(() => setCopyStatus(null), 3000);
    }
  }, [formattedText, sanitizedFileName, calculateSize]);

  const canShare = typeof navigator !== 'undefined' && 'share' in navigator;

  const handleWebShare = useCallback(async () => {
    if (!canShare) {
      setShareStatus('Web Share API не поддерживается вашим браузером');
      setTimeout(() => setShareStatus(null), 3000);
      return;
    }

    try {
      await navigator.share({
        title: documentTitle,
        text: formattedText,
      });
      setSuccessState({
        type: 'share',
        fileName: sanitizedFileName,
        fileSize: calculateSize(formattedText),
        timestamp: new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }),
      });
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        console.error('Failed to share:', err);
        setShareStatus('Ошибка при отправке');
        setTimeout(() => setShareStatus(null), 3000);
      }
    }
  }, [canShare, documentTitle, formattedText, sanitizedFileName, calculateSize]);

  return (
    <main className="export-page" id="main-content" tabIndex={-1}>
      <header className="page-heading export-heading">
        <div className="export-heading__title">
          <p className="eyebrow">Публикация и Сохранение</p>
          <h1>Экспорт документа</h1>
          <p>Выберите формат экспорта, параметры разметки и метаданных для сохранения распознанного текста.</p>
        </div>

        {copyStatus && <Status tone="success">{copyStatus}</Status>}
        {shareStatus && <Status tone="warning">{shareStatus}</Status>}
      </header>

      <div className="export-layout">
        {/* Left Column: Formats & Options */}
        <div className="export-controls">
          {/* Success Banner/Card if action performed */}
          {successState && (
            <Card className="export-success-card">
              <div className="export-success-card__header">
                <div className="export-success-card__icon">
                  <Icon name="document" />
                </div>
                <div>
                  <Badge tone="success">
                    {successState.type === 'download'
                      ? 'Файл скачан'
                      : successState.type === 'copy'
                      ? 'Скопировано в буфер'
                      : 'Отправлено'}
                  </Badge>
                  <h3>Экспорт выполнен успешно</h3>
                </div>
              </div>

              <div className="export-success-card__details">
                <div className="export-detail-item">
                  <span className="export-detail-item__label">Файл:</span>
                  <strong className="export-detail-item__val">{successState.fileName}</strong>
                </div>
                <div className="export-detail-item">
                  <span className="export-detail-item__label">Формат и размер:</span>
                  <span>TXT • {successState.fileSize}</span>
                </div>
                <div className="export-detail-item">
                  <span className="export-detail-item__label">Время:</span>
                  <span>{successState.timestamp}</span>
                </div>
              </div>

              <div className="export-success-card__actions">
                <Button variant="secondary" onClick={handleDownloadTxt}>
                  Открыть / Скачать снова
                </Button>
                <Link className="ui-button ui-button--primary" to="/documents">
                  Готово (к документам)
                </Link>
              </div>
            </Card>
          )}

          {/* Formats Section */}
          <Card className="export-section-card">
            <h2>Форматы экспорта (V1)</h2>
            <p className="export-section-desc">Доступны быстрые форматы скачивания и копирования текстовых данных.</p>

            <div className="export-formats-grid">
              <div className="export-format-item">
                <div className="export-format-item__info">
                  <Icon name="document" />
                  <div>
                    <strong>Текстовый файл (TXT)</strong>
                    <p>Простой текстовый формат UTF-8 с сохранениями строк</p>
                  </div>
                </div>
                <Button variant="primary" onClick={handleDownloadTxt}>
                  Скачать TXT
                </Button>
              </div>

              <div className="export-format-item">
                <div className="export-format-item__info">
                  <Icon name="sparkles" />
                  <div>
                    <strong>Буфер обмена</strong>
                    <p>Мгновенное копирование всего готового текста</p>
                  </div>
                </div>
                <Button variant="secondary" onClick={handleCopyToClipboard}>
                  Скопировать
                </Button>
              </div>

              <div className="export-format-item">
                <div className="export-format-item__info">
                  <Icon name="arrow" />
                  <div>
                    <strong>Поделиться (Web Share)</strong>
                    <p>Отправить текст в сторонние приложения</p>
                  </div>
                </div>
                <Button
                  variant="secondary"
                  disabled={!canShare}
                  onClick={handleWebShare}
                  title={!canShare ? 'Не поддерживается вашим браузером' : undefined}
                >
                  Поделиться
                </Button>
              </div>

              {/* Locked Formats */}
              <div className="export-format-item export-format-item--disabled">
                <div className="export-format-item__info">
                  <Icon name="document" />
                  <div>
                    <div className="export-format-item__title-row">
                      <strong>Документ PDF</strong>
                      <Badge tone="info">Скоро</Badge>
                    </div>
                    <p>Форматированный документ с оригинальным рукописным фоном</p>
                  </div>
                </div>
                <Button variant="secondary" disabled>
                  Скачать PDF
                </Button>
              </div>

              <div className="export-format-item export-format-item--disabled">
                <div className="export-format-item__info">
                  <Icon name="document" />
                  <div>
                    <div className="export-format-item__title-row">
                      <strong>Документ Microsoft Word (DOCX)</strong>
                      <Badge tone="info">Скоро</Badge>
                    </div>
                    <p>Документ с таблицей оригиналов и распознанного текста</p>
                  </div>
                </div>
                <Button variant="secondary" disabled>
                  Скачать DOCX
                </Button>
              </div>
            </div>
          </Card>

          {/* Options Section */}
          <Card className="export-section-card">
            <h2>Опции экспорта</h2>
            <p className="export-section-desc">Настройте состав и структуру экспортируемого содержимого.</p>

            <div className="export-options-list">
              <label className="export-checkbox-option">
                <input
                  type="checkbox"
                  checked={preserveLineBreaks}
                  onChange={(e) => setPreserveLineBreaks(e.target.checked)}
                />
                <div className="export-checkbox-option__text">
                  <strong>Сохранять переносы строк</strong>
                  <p>Сохраняет исходное разбиение рукописных строк документа</p>
                </div>
              </label>

              <label className="export-checkbox-option">
                <input
                  type="checkbox"
                  checked={includeTitle}
                  onChange={(e) => setIncludeTitle(e.target.checked)}
                />
                <div className="export-checkbox-option__text">
                  <strong>Включить название документа</strong>
                  <p>Добавляет заголовок документа в первую строку файла</p>
                </div>
              </label>

              <label className="export-checkbox-option">
                <input
                  type="checkbox"
                  checked={includeMetadata}
                  onChange={(e) => setIncludeMetadata(e.target.checked)}
                />
                <div className="export-checkbox-option__text">
                  <strong>Включить дату и метаданные</strong>
                  <p>Добавляет системную информацию и дату проведения экспорта</p>
                </div>
              </label>
            </div>
          </Card>
        </div>

        {/* Right Column: Live Preview */}
        <div className="export-preview-column">
          <Card className="export-preview-card">
            <div className="export-preview-card__header">
              <div>
                <h2>Live Предпросмотр</h2>
                <p>Предварительный вид готового экспортируемого файла</p>
              </div>
              <div className="export-preview-stats">
                <span>{textStats.lines} стр.</span>
                <span>•</span>
                <span>{textStats.words} слов</span>
                <span>•</span>
                <span>{textStats.chars} симв.</span>
              </div>
            </div>

            <div className="export-preview-box">
              <pre className="export-preview-content">{formattedText}</pre>
            </div>

            <div className="export-preview-card__footer">
              <Button variant="secondary" onClick={handleCopyToClipboard}>
                Скопировать из предпросмотра
              </Button>
              <Button variant="primary" onClick={handleDownloadTxt}>
                Скачать TXT
              </Button>
            </div>
          </Card>
        </div>
      </div>
    </main>
  );
}
