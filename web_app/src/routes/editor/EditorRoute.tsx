import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import {
  calculateTextStats,
  loadEditorState,
  saveEditorState,
  type LineBlock,
} from '@features/editor';
import { Badge, Button, Card, Icon, Status, Tabs, type TabItem } from '@shared/ui';

export default function EditorRoute() {
  const [searchParams] = useSearchParams();
  const jobId = searchParams.get('jobId');
  const documentId = searchParams.get('documentId');
  const docOrJobId = jobId || documentId || undefined;

  // Tabs / view mode state
  const [activeTab, setActiveTab] = useState<string>('split');

  // Blocks & History state
  const [blocks, setBlocks] = useState<LineBlock[]>(() => loadEditorState(docOrJobId));
  const [past, setPast] = useState<LineBlock[][]>([]);
  const [future, setFuture] = useState<LineBlock[][]>([]);

  // Selection & Auto-save state
  const [selectedLineId, setSelectedLineId] = useState<string | null>('line-1');
  const [isDirty, setIsDirty] = useState<boolean>(false);
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(new Date());

  // References for scrolling split view
  const lineRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // Helper to push history
  const updateBlocks = useCallback(
    (newBlocks: LineBlock[] | ((prev: LineBlock[]) => LineBlock[])) => {
      setBlocks((prevBlocks) => {
        const nextBlocks = typeof newBlocks === 'function' ? newBlocks(prevBlocks) : newBlocks;
        setPast((p) => [...p, prevBlocks]);
        setFuture([]);
        setIsDirty(true);
        return nextBlocks;
      });
    },
    [],
  );

  // Undo / Redo
  const handleUndo = useCallback(() => {
    if (past.length === 0) return;
    const previous = past[past.length - 1];
    const newPast = past.slice(0, past.length - 1);
    setFuture((f) => [blocks, ...f]);
    setBlocks(previous);
    setPast(newPast);
    setIsDirty(true);
  }, [past, blocks]);

  const handleRedo = useCallback(() => {
    if (future.length === 0) return;
    const next = future[0];
    const newFuture = future.slice(1);
    setPast((p) => [...p, blocks]);
    setBlocks(next);
    setFuture(newFuture);
    setIsDirty(true);
  }, [future, blocks]);

  // Auto-save effect (every 3 seconds)
  useEffect(() => {
    if (!isDirty) return;

    const timer = window.setInterval(() => {
      saveEditorState(blocks, docOrJobId);
      setIsDirty(false);
      setLastSavedAt(new Date());
    }, 3000);

    return () => window.clearInterval(timer);
  }, [blocks, isDirty, docOrJobId]);

  // Manual save handler
  const handleManualSave = useCallback(() => {
    saveEditorState(blocks, docOrJobId);
    setIsDirty(false);
    setLastSavedAt(new Date());
  }, [blocks, docOrJobId]);

  // Line text update
  const handleLineTextChange = useCallback(
    (id: string, newText: string) => {
      updateBlocks((prev) =>
        prev.map((b) => {
          if (b.id !== id) return b;
          const status = newText === b.rawText ? 'unverified' : 'edited';
          return { ...b, editedText: newText, status };
        }),
      );
    },
    [updateBlocks],
  );

  // Line status update
  const handleLineStatusChange = useCallback(
    (id: string, newStatus: LineBlock['status']) => {
      updateBlocks((prev) =>
        prev.map((b) => (b.id === id ? { ...b, status: newStatus } : b)),
      );
    },
    [updateBlocks],
  );

  // Line reset
  const handleLineReset = useCallback(
    (id: string) => {
      updateBlocks((prev) =>
        prev.map((b) =>
          b.id === id ? { ...b, editedText: b.rawText, status: 'unverified' } : b,
        ),
      );
    },
    [updateBlocks],
  );

  // Full text change for Mode 1 ("Только текст")
  const handleFullTextChange = useCallback(
    (fullText: string) => {
      const lines = fullText.split('\n');
      updateBlocks((prev) => {
        return lines.map((lineText, idx) => {
          const existing = prev[idx];
          if (existing) {
            const status = lineText === existing.rawText ? existing.status : 'edited';
            return { ...existing, editedText: lineText, status };
          }
          return {
            id: `line-${idx + 1}`,
            lineNumber: idx + 1,
            rawText: lineText,
            editedText: lineText,
            confidence: 0.9,
            status: 'edited',
            box: { x: 5, y: 10 + idx * 15, width: 90, height: 12 },
          };
        });
      });
    },
    [updateBlocks],
  );

  // Scroll into view helper
  const handleSelectLine = useCallback((id: string) => {
    setSelectedLineId(id);
    const element = lineRefs.current[id];
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, []);

  // Stats calculation
  const stats = useMemo(() => calculateTextStats(blocks), [blocks]);
  const fullTextValue = useMemo(() => blocks.map((b) => b.editedText).join('\n'), [blocks]);

  // Links for navigation
  const querySuffix = docOrJobId ? `?jobId=${encodeURIComponent(docOrJobId)}` : '';
  const reviewUrl = `/review${querySuffix}`;
  const exportUrl = `/export${querySuffix}`;

  // Tab items setup
  const tabItems: TabItem[] = [
    {
      id: 'text-only',
      label: 'Только текст',
      panel: (
        <div className="editor-mode-text-only">
          <div className="editor-textarea-header">
            <span>Прямое редактирование всего текста документа</span>
            <Badge tone="info">{blocks.length} строк</Badge>
          </div>
          <textarea
            className="editor-full-textarea"
            value={fullTextValue}
            onChange={(e) => handleFullTextChange(e.target.value)}
            placeholder="Введите или отредактируйте распознанный текст..."
            rows={14}
          />
          <div className="editor-lines-summary">
            <h4>Статус строк:</h4>
            <div className="editor-lines-summary-grid">
              {blocks.map((block) => (
                <div
                  key={block.id}
                  className={`editor-summary-chip editor-summary-chip--${block.status}`}
                >
                  <span>#{block.lineNumber}</span>
                  <span className="editor-summary-chip__text">{block.editedText}</span>
                  <Badge
                    tone={
                      block.status === 'verified'
                        ? 'success'
                        : block.status === 'edited'
                        ? 'info'
                        : 'warning'
                    }
                  >
                    {block.status === 'verified'
                      ? 'Проверено'
                      : block.status === 'edited'
                      ? 'Изменено'
                      : 'Не проверено'}
                  </Badge>
                </div>
              ))}
            </div>
          </div>
        </div>
      ),
    },
    {
      id: 'split',
      label: 'Оригинал и текст',
      panel: (
        <div className="editor-mode-split">
          {/* Left panel: Original Page Preview */}
          <div className="editor-split-left">
            <div className="editor-split-panel-header">
              <Icon name="file" />
              <span>Оригинал рукописи</span>
            </div>
            <div className="editor-document-preview">
              <div className="editor-manuscript-canvas">
                <div className="editor-manuscript-paper">
                  <div className="editor-manuscript-header-mock">
                    <span className="manuscript-stamp">HTR ARCHIVE 1928</span>
                    <span className="manuscript-title">ТАҶРИБАИ РУКОПИС</span>
                  </div>
                  {blocks.map((block) => {
                    const isSelected = selectedLineId === block.id;
                    const box = block.box || { x: 5, y: 10 + block.lineNumber * 15, width: 90, height: 12 };
                    return (
                      <div
                        key={block.id}
                        className={`editor-manuscript-line-box ${
                          isSelected ? 'editor-manuscript-line-box--selected' : ''
                        }`}
                        style={{
                          left: `${box.x}%`,
                          top: `${box.y}%`,
                          width: `${box.width}%`,
                          height: `${box.height}%`,
                        }}
                        onClick={() => handleSelectLine(block.id)}
                        role="button"
                        tabIndex={0}
                        title={`Строка ${block.lineNumber}: ${block.editedText}`}
                      >
                        <span className="line-box-number">#{block.lineNumber}</span>
                        <span className="line-box-handwriting">{block.rawText}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>

          {/* Right panel: Editor */}
          <div className="editor-split-right">
            <div className="editor-split-panel-header">
              <Icon name="edit" />
              <span>Редактор строк</span>
            </div>
            <div className="editor-split-lines-list">
              {blocks.map((block) => {
                const isSelected = selectedLineId === block.id;
                return (
                  <div
                    key={block.id}
                    ref={(el) => {
                      lineRefs.current[block.id] = el;
                    }}
                    className={`editor-line-row ${
                      isSelected ? 'editor-line-row--selected' : ''
                    }`}
                    onClick={() => setSelectedLineId(block.id)}
                  >
                    <div className="editor-line-row__meta">
                      <span className="editor-line-badge">Строка {block.lineNumber}</span>
                      <span className="editor-line-confidence">
                        Уверенность: {Math.round(block.confidence * 100)}%
                      </span>
                      <Badge
                        tone={
                          block.status === 'verified'
                            ? 'success'
                            : block.status === 'edited'
                            ? 'info'
                            : 'warning'
                        }
                      >
                        {block.status === 'verified'
                          ? 'Подтверждено'
                          : block.status === 'edited'
                          ? 'Изменено'
                          : 'Не проверено'}
                      </Badge>
                    </div>
                    <div className="editor-line-row__content">
                      <input
                        type="text"
                        className="editor-line-input"
                        value={block.editedText}
                        onChange={(e) => handleLineTextChange(block.id, e.target.value)}
                        placeholder="Текст строки..."
                      />
                      <div className="editor-line-row__actions">
                        <Button
                          variant={block.status === 'verified' ? 'primary' : 'secondary'}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleLineStatusChange(
                              block.id,
                              block.status === 'verified' ? 'unverified' : 'verified',
                            );
                          }}
                        >
                          {block.status === 'verified' ? '✓ Проверено' : 'Подтвердить'}
                        </Button>
                        {block.editedText !== block.rawText ? (
                          <Button
                            variant="quiet"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleLineReset(block.id);
                            }}
                          >
                            Сбросить
                          </Button>
                        ) : null}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      ),
    },
    {
      id: 'line-by-line',
      label: 'Построчная проверка',
      panel: (
        <div className="editor-mode-cards">
          <div className="editor-cards-grid">
            {blocks.map((block) => (
              <Card key={block.id} className="editor-line-card">
                <div className="editor-line-card__header">
                  <div className="editor-line-card__title">
                    <span className="editor-line-card__num">Строка #{block.lineNumber}</span>
                    <span className="editor-line-card__conf">
                      Уверенность {Math.round(block.confidence * 100)}%
                    </span>
                  </div>
                  <Badge
                    tone={
                      block.status === 'verified'
                        ? 'success'
                        : block.status === 'edited'
                        ? 'info'
                        : 'warning'
                    }
                  >
                    {block.status === 'verified'
                      ? 'Подтверждено'
                      : block.status === 'edited'
                      ? 'Изменено'
                      : 'Не проверено'}
                  </Badge>
                </div>

                <div className="editor-line-card__snippet">
                  <div className="snippet-label">Фрагмент оригинала (HTR Crop):</div>
                  <div className="snippet-box">
                    <span className="snippet-handwritten">{block.rawText}</span>
                  </div>
                </div>

                <div className="editor-line-card__edit">
                  <label htmlFor={`input-${block.id}`} className="ui-field__label">
                    Распознанный текст:
                  </label>
                  <input
                    id={`input-${block.id}`}
                    type="text"
                    className="editor-line-input"
                    value={block.editedText}
                    onChange={(e) => handleLineTextChange(block.id, e.target.value)}
                  />
                </div>

                <div className="editor-line-card__footer">
                  <Button
                    variant={block.status === 'verified' ? 'primary' : 'secondary'}
                    onClick={() =>
                      handleLineStatusChange(
                        block.id,
                        block.status === 'verified' ? 'unverified' : 'verified',
                      )
                    }
                  >
                    {block.status === 'verified' ? '✓ Подтверждено' : 'Подтвердить'}
                  </Button>
                  <Button
                    variant="quiet"
                    disabled={block.editedText === block.rawText && block.status === 'unverified'}
                    onClick={() => handleLineReset(block.id)}
                  >
                    Сбросить
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        </div>
      ),
    },
  ];

  return (
    <main className="editor-page" id="main-content" tabIndex={-1}>
      <header className="page-heading editor-heading">
        <div className="editor-heading__title">
          <p className="eyebrow">Интерактивная корректура Tajik HTR</p>
          <h1>Редактор транскрипции</h1>
          <p>Проверка и редактирование распознанного текста рукописных документов.</p>
        </div>

        <div className="editor-heading__status">
          {isDirty ? (
            <Status tone="warning">Есть несохранённые изменения</Status>
          ) : (
            <Status tone="success">
              Сохранено {lastSavedAt ? `в ${lastSavedAt.toLocaleTimeString()}` : ''}
            </Status>
          )}
        </div>
      </header>

      <Card className="editor-main-card">
        <Tabs items={tabItems} activeId={activeTab} onChange={setActiveTab} />
      </Card>

      {/* Action Bar */}
      <div className="editor-bottom-bar">
        <div className="editor-bar-group">
          <Button variant="secondary" disabled={past.length === 0} onClick={handleUndo}>
            Отменить
          </Button>
          <Button variant="secondary" disabled={future.length === 0} onClick={handleRedo}>
            Вернуть
          </Button>
          <Button variant="primary" onClick={handleManualSave}>
            Сохранить вручную
          </Button>
        </div>

        <div className="editor-bar-stats">
          <span>
            Слов: <strong>{stats.words}</strong>
          </span>
          <span className="stats-divider">•</span>
          <span>
            Символов: <strong>{stats.characters}</strong>
          </span>
        </div>

        <div className="editor-bar-links">
          <Link className="ui-button ui-button--quiet" to={reviewUrl}>
            Проверить таджикские буквы
          </Link>
          <Link className="ui-button ui-button--secondary" to={exportUrl}>
            Экспорт
          </Link>
        </div>
      </div>
    </main>
  );
}
