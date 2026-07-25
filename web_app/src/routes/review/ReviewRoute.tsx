import { useCallback, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { loadEditorState, saveEditorState, type LineBlock } from '@features/editor';
import { TajikPanel } from '@features/tajik-panel';
import { Badge, Button, Card, Icon, Status } from '@shared/ui';

export interface Suggestion {
  id: string;
  blockId: string;
  lineNumber: number;
  wordIndex: number;
  originalWord: string;
  suggestedWord: string;
  targetChar: string;
  replacementChar: string;
  lineContext: string;
  status: 'pending' | 'accepted' | 'rejected' | 'skipped';
}

// Russian to Tajik letter replacement mapping
const CYRILLIC_TO_TAJIK_MAP: Record<string, string> = {
  г: 'ғ',
  Г: 'Ғ',
  и: 'ӣ',
  И: 'Ӣ',
  к: 'қ',
  К: 'Қ',
  у: 'ӯ',
  У: 'Ӯ',
  х: 'ҳ',
  Х: 'Ҳ',
  ч: 'ҷ',
  Ч: 'Ҷ',
};

const DEFAULT_REVIEW_LINES: LineBlock[] = [
  {
    id: 'line-1',
    lineNumber: 1,
    rawText: 'Ба номи Худованди бахшандаи мехрубон',
    editedText: 'Ба номи Худованди бахшандаи мехрубон',
    confidence: 0.95,
    status: 'unverified',
  },
  {
    id: 'line-2',
    lineNumber: 2,
    rawText: 'Сахифаи 1 аз рукописи чашм ва хуршед',
    editedText: 'Сахифаи 1 аз рукописи чашм ва хуршед',
    confidence: 0.88,
    status: 'unverified',
  },
  {
    id: 'line-3',
    lineNumber: 3,
    rawText: 'Дастхати таьрихии адабиети точик ва китоб',
    editedText: 'Дастхати таьрихии адабиети точик ва китоб',
    confidence: 0.89,
    status: 'unverified',
  },
  {
    id: 'line-4',
    lineNumber: 4,
    rawText: 'Транскрипсия ва тасхехи матни дастии кадим',
    editedText: 'Транскрипсия ва тасхехи матни дастии кадим',
    confidence: 0.92,
    status: 'unverified',
  },
  {
    id: 'line-5',
    lineNumber: 5,
    rawText: 'Омузиш ва баррасии осори ниьогон дар озмоишгох',
    editedText: 'Омузиш ва баррасии осори ниьогон дар озмоишгох',
    confidence: 0.85,
    status: 'unverified',
  },
];

/**
 * Generates initial suggestions by searching for Russian letters (г, и, к, у, х, ч)
 * inside words of each line block.
 */
function generateSuggestionsFromBlocks(blocks: LineBlock[]): Suggestion[] {
  const suggestions: Suggestion[] = [];
  let counter = 0;

  for (const block of blocks) {
    const text = block.editedText || block.rawText;
    const words = text.split(/\s+/);

    words.forEach((word, wIdx) => {
      // Find candidate Russian letters in this word
      for (let i = 0; i < word.length; i++) {
        const char = word[i] ?? '';
        const replacement = CYRILLIC_TO_TAJIK_MAP[char];

        if (replacement) {
          counter++;
          const suggestedWord =
            word.slice(0, i) + replacement + word.slice(i + 1);

          suggestions.push({
            id: `sug-${counter}`,
            blockId: block.id,
            lineNumber: block.lineNumber,
            wordIndex: wIdx,
            originalWord: word,
            suggestedWord,
            targetChar: char,
            replacementChar: replacement,
            lineContext: text,
            status: 'pending',
          });
        }
      }
    });
  }

  return suggestions;
}

export default function ReviewRoute() {
  const [searchParams] = useSearchParams();
  const documentId = searchParams.get('documentId');
  const jobId = searchParams.get('jobId');
  const docOrJobId = documentId || jobId || undefined;

  // Load line blocks from localStorage or fallback
  const [blocks, setBlocks] = useState<LineBlock[]>(() => {
    const loaded = loadEditorState(docOrJobId);
    if (!loaded || loaded.length === 0) {
      return DEFAULT_REVIEW_LINES;
    }
    return loaded;
  });

  // Generate initial suggestions
  const [suggestions, setSuggestions] = useState<Suggestion[]>(() =>
    generateSuggestionsFromBlocks(blocks),
  );

  // Active suggestion index in carousel
  const [currentIndex, setCurrentIndex] = useState<number>(0);
  const [correctionsCount, setCorrectionsCount] = useState<number>(0);
  const [customWordOverride, setCustomWordOverride] = useState<string>('');
  const [isFinished, setIsFinished] = useState<boolean>(false);

  // Stats calculation
  const totalCount = suggestions.length;
  const processedCount = useMemo(
    () => suggestions.filter((s) => s.status !== 'pending').length,
    [suggestions],
  );
  const progressPercent = totalCount > 0 ? Math.round((processedCount / totalCount) * 100) : 100;

  const currentSuggestion = suggestions[currentIndex];

  // Helper to persist blocks state
  const saveBlocks = useCallback(
    (newBlocks: LineBlock[]) => {
      setBlocks(newBlocks);
      saveEditorState(newBlocks, docOrJobId);
    },
    [docOrJobId],
  );

  // Move to next pending or simply next suggestion index
  const goToNextSuggestion = useCallback(() => {
    if (currentIndex < suggestions.length - 1) {
      setCurrentIndex((prev) => prev + 1);
      setCustomWordOverride('');
    } else {
      setIsFinished(true);
    }
  }, [currentIndex, suggestions.length]);

  // Handle "Исправить" (Correct) action
  const handleAccept = useCallback(
    (customReplacement?: string) => {
      if (!currentSuggestion) return;

      const replacementWord = customReplacement || customWordOverride || currentSuggestion.suggestedWord;

      // Update blocks with the new word
      const updatedBlocks = blocks.map((b) => {
        if (b.id !== currentSuggestion.blockId) return b;
        const words = b.editedText.split(/\s+/);
        if (words[currentSuggestion.wordIndex] !== undefined) {
          words[currentSuggestion.wordIndex] = replacementWord;
        }
        return { ...b, editedText: words.join(' '), status: 'edited' as const };
      });

      saveBlocks(updatedBlocks);

      // Update suggestion status
      setSuggestions((prev) =>
        prev.map((s, idx) =>
          idx === currentIndex
            ? { ...s, status: 'accepted', suggestedWord: replacementWord }
            : s,
        ),
      );

      setCorrectionsCount((prev) => prev + 1);
      goToNextSuggestion();
    },
    [blocks, currentSuggestion, currentIndex, customWordOverride, saveBlocks, goToNextSuggestion],
  );

  // Handle "Оставить" (Keep original) action
  const handleReject = useCallback(() => {
    if (!currentSuggestion) return;

    setSuggestions((prev) =>
      prev.map((s, idx) => (idx === currentIndex ? { ...s, status: 'rejected' } : s)),
    );

    goToNextSuggestion();
  }, [currentSuggestion, currentIndex, goToNextSuggestion]);

  // Handle "Пропустить" (Skip) action
  const handleSkip = useCallback(() => {
    if (!currentSuggestion) return;

    setSuggestions((prev) =>
      prev.map((s, idx) => (idx === currentIndex ? { ...s, status: 'skipped' } : s)),
    );

    goToNextSuggestion();
  }, [currentSuggestion, currentIndex, goToNextSuggestion]);

  // TajikPanel callback: Insert character
  const handleInsertChar = useCallback(
    (char: string) => {
      const activeWord = customWordOverride || currentSuggestion?.suggestedWord || '';
      setCustomWordOverride(activeWord + char);
    },
    [customWordOverride, currentSuggestion],
  );

  // TajikPanel callback: Replace character in current suggestion
  const handleReplaceHere = useCallback(
    (from: string, to: string) => {
      const activeWord = customWordOverride || currentSuggestion?.suggestedWord || currentSuggestion?.originalWord || '';
      const updatedWord = activeWord.replace(from, to);
      setCustomWordOverride(updatedWord);
    },
    [customWordOverride, currentSuggestion],
  );

  // TajikPanel callback: Replace character in all blocks & document
  const handleReplaceAll = useCallback(
    (from: string, to: string) => {
      let count = 0;
      const updatedBlocks = blocks.map((b) => {
        const regex = new RegExp(from, 'g');
        const matches = (b.editedText.match(regex) || []).length;
        count += matches;
        const newText = b.editedText.replace(regex, to);
        return { ...b, editedText: newText, status: matches > 0 ? ('edited' as const) : b.status };
      });

      saveBlocks(updatedBlocks);
      setCorrectionsCount((prev) => prev + count);

      // Re-generate suggestions for updated text
      const newSuggestions = generateSuggestionsFromBlocks(updatedBlocks);
      setSuggestions(newSuggestions);
      setCurrentIndex(0);
      setCustomWordOverride('');
    },
    [blocks, saveBlocks],
  );

  // Editor Link URL
  const editorUrl = docOrJobId
    ? `/editor?${documentId ? `documentId=${encodeURIComponent(documentId)}` : `jobId=${encodeURIComponent(jobId || '')}`}`
    : '/editor';

  return (
    <main className="review-page" id="main-content" tabIndex={-1}>
      <header className="page-heading review-heading">
        <div>
          <p className="eyebrow">Модуль проверки Tajik HTR</p>
          <h1>Проверка таджикских букв</h1>
          <p>
            Автоматическое выявление и корректура кириллических букв (г, и, к, у, х, ч) в
            распознанном рукописном тексте.
          </p>
        </div>
        <div className="review-heading__actions">
          <Link className="ui-button ui-button--secondary" to={editorUrl}>
            Вернуться в редактор
          </Link>
        </div>
      </header>

      {/* Progress Bar Card */}
      <Card className="review-progress-card">
        <div className="review-progress-card__header">
          <div className="review-progress-card__title">
            <Icon name="sparkles" />
            <strong>Прогресс проверки</strong>
          </div>
          <Badge tone={isFinished || processedCount === totalCount ? 'success' : 'info'}>
            {processedCount} из {totalCount} проверено ({progressPercent}%)
          </Badge>
        </div>
        <div className="review-progress-bar" role="progressbar" aria-valuenow={progressPercent} aria-valuemin={0} aria-valuemax={100}>
          <div
            className="review-progress-fill"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </Card>

      {/* Main Review Body */}
      {!isFinished && currentSuggestion ? (
        <Card className="review-card">
          <div className="review-card__header">
            <div className="review-card__step">
              <span>Предложение {currentIndex + 1} из {totalCount}</span>
              <span className="review-card__line-num">Строка #{currentSuggestion.lineNumber}</span>
            </div>
            <Badge tone="warning">Требует внимания</Badge>
          </div>

          <div className="review-card__body">
            {/* Word comparison */}
            <div className="review-card__word-comparison">
              <div className="review-word-box review-word-box--original">
                <span className="review-word-box__label">Исходное слово:</span>
                <span className="review-word-box__value">{currentSuggestion.originalWord}</span>
              </div>

              <div className="review-word-arrow" aria-hidden="true">
                →
              </div>

              <div className="review-word-box review-word-box--suggested">
                <span className="review-word-box__label">Предлагаемая замена ({currentSuggestion.targetChar} → {currentSuggestion.replacementChar}):</span>
                <input
                  type="text"
                  className="review-word-input"
                  value={customWordOverride || currentSuggestion.suggestedWord}
                  onChange={(e) => setCustomWordOverride(e.target.value)}
                  placeholder="Вариант замены..."
                />
              </div>
            </div>

            {/* Line context display */}
            <div className="review-card__context">
              <span className="context-label">Контекст строки:</span>
              <p className="context-text">
                «
                {currentSuggestion.lineContext.split(/\s+/).map((w, idx) => {
                  const isTarget = idx === currentSuggestion.wordIndex;
                  return isTarget ? (
                    <mark key={idx} className="review-highlight">
                      {w}
                    </mark>
                  ) : (
                    ` ${w} `
                  );
                })}
                »
              </p>
            </div>

            {/* Decision Action Buttons */}
            <div className="review-card__actions">
              <div className="review-card__actions-primary">
                <Button variant="primary" onClick={() => handleAccept()}>
                  ✓ Исправить
                </Button>
                <Button variant="secondary" onClick={handleReject}>
                  Оставить
                </Button>
                <Button variant="quiet" onClick={handleSkip}>
                  Пропустить
                </Button>
              </div>

              <div className="review-card__actions-nav">
                <Button
                  variant="quiet"
                  disabled={currentIndex === 0}
                  onClick={() => {
                    setCurrentIndex((prev) => Math.max(0, prev - 1));
                    setCustomWordOverride('');
                  }}
                >
                  ← Назад
                </Button>
                <Button
                  variant="quiet"
                  disabled={currentIndex >= totalCount - 1}
                  onClick={() => {
                    setCurrentIndex((prev) => Math.min(totalCount - 1, prev + 1));
                    setCustomWordOverride('');
                  }}
                >
                  Вперёд →
                </Button>
              </div>
            </div>
          </div>
        </Card>
      ) : (
        /* Final completion screen */
        <Card className="review-final-card">
          <div className="review-final-card__icon">🎉</div>
          <h2>Проверка таджикских букв завершена!</h2>
          <p className="review-final-card__summary">
            Все потенциально ошибочные кириллические буквы были проверены.
          </p>

          <div className="review-final-card__stats">
            <div className="stat-item">
              <span className="stat-value">{correctionsCount}</span>
              <span className="stat-label">Внесено правок</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">{totalCount}</span>
              <span className="stat-label">Всего предложений</span>
            </div>
          </div>

          <div className="review-final-card__preview">
            <h4>Итоговый проверенный текст:</h4>
            <div className="review-final-text-box">
              {blocks.map((b) => (
                <div key={b.id} className="review-final-line">
                  <span className="review-final-line-num">#{b.lineNumber}</span>
                  <span className="review-final-line-text">{b.editedText}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="review-final-card__actions">
            <Link className="ui-button ui-button--primary" to={editorUrl}>
              Вернуться в редактор
            </Link>
            <Button
              variant="secondary"
              onClick={() => {
                setIsFinished(false);
                setCurrentIndex(0);
              }}
            >
              Перепроверить снова
            </Button>
          </div>
        </Card>
      )}

      {/* Integrated TajikPanel at the bottom */}
      <Card className="review-panel-card">
        <TajikPanel
          activeText={
            currentSuggestion
              ? customWordOverride || currentSuggestion.suggestedWord || currentSuggestion.originalWord
              : ''
          }
          onInsert={handleInsertChar}
          onReplaceHere={handleReplaceHere}
          onReplaceAll={handleReplaceAll}
        />
      </Card>
    </main>
  );
}
