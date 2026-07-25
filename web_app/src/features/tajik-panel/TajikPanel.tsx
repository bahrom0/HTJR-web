import React from 'react';
import { Badge, Button } from '@shared/ui';

export interface TajikPanelProps {
  activeText?: string;
  onInsert: (char: string) => void;
  onReplaceHere?: (from: string, to: string) => void;
  onReplaceAll?: (from: string, to: string) => void;
  className?: string;
}

export interface TajikCharPair {
  upper: string;
  lower: string;
  baseUpper: string;
  baseLower: string;
  name: string;
}

export const TAJIK_CHAR_PAIRS: TajikCharPair[] = [
  { upper: 'Ғ', lower: 'ғ', baseUpper: 'Г', baseLower: 'г', name: 'Ғе' },
  { upper: 'Ӣ', lower: 'ӣ', baseUpper: 'И', baseLower: 'и', name: 'Ӣ-и дароз' },
  { upper: 'Қ', lower: 'қ', baseUpper: 'К', baseLower: 'к', name: 'Қоф' },
  { upper: 'Ӯ', lower: 'ӯ', baseUpper: 'У', baseLower: 'у', name: 'Ӯ-и маъруф' },
  { upper: 'Ҳ', lower: 'ҳ', baseUpper: 'Х', baseLower: 'х', name: 'Ҳо' },
  { upper: 'Ҷ', lower: 'ҷ', baseUpper: 'Ч', baseLower: 'ч', name: 'Ҷим' },
];

export function TajikPanel({
  activeText = '',
  onInsert,
  onReplaceHere,
  onReplaceAll,
  className = '',
}: TajikPanelProps) {
  // Find which base characters exist in activeText for contextual replacement suggestions
  const activeReplacements = React.useMemo(() => {
    if (!activeText) return [];
    const found: Array<{ from: string; to: string; label: string }> = [];

    for (const pair of TAJIK_CHAR_PAIRS) {
      if (activeText.includes(pair.baseLower)) {
        found.push({
          from: pair.baseLower,
          to: pair.lower,
          label: `${pair.baseLower} → ${pair.lower}`,
        });
      }
      if (activeText.includes(pair.baseUpper)) {
        found.push({
          from: pair.baseUpper,
          to: pair.upper,
          label: `${pair.baseUpper} → ${pair.upper}`,
        });
      }
    }
    return found;
  }, [activeText]);

  return (
    <div className={`tajik-panel ${className}`.trim()}>
      <div className="tajik-panel__header">
        <div className="tajik-panel__title">
          <span className="tajik-panel__icon" aria-hidden="true">
            ⌨️
          </span>
          <strong>Панель таджикских букв</strong>
          <Badge tone="info">Ғ Ӣ Қ Ӯ Ҳ Ҷ</Badge>
        </div>
        <span className="tajik-panel__hint">
          Кликните по букве для вставки или заменяйте ошибочные кириллические буквы
        </span>
      </div>

      <div className="tajik-panel__grid">
        {TAJIK_CHAR_PAIRS.map((pair) => (
          <div key={pair.upper} className="tajik-panel__char-group">
            <button
              type="button"
              className="tajik-panel__char-btn"
              onClick={() => onInsert(pair.upper)}
              title={`Вставить ${pair.upper} (${pair.name})`}
            >
              {pair.upper}
            </button>
            <button
              type="button"
              className="tajik-panel__char-btn"
              onClick={() => onInsert(pair.lower)}
              title={`Вставить ${pair.lower} (${pair.name})`}
            >
              {pair.lower}
            </button>
          </div>
        ))}
      </div>

      {activeReplacements.length > 0 && (onReplaceHere || onReplaceAll) && (
        <div className="tajik-panel__replacements">
          <span className="tajik-panel__replacements-label">
            Замена букв в выбранном слове («{activeText}»):
          </span>
          <div className="tajik-panel__replacements-list">
            {activeReplacements.map((item) => (
              <div key={`${item.from}-${item.to}`} className="tajik-panel__replacement-item">
                <span className="tajik-panel__replacement-badge">{item.label}</span>
                {onReplaceHere && (
                  <Button
                    variant="secondary"
                    onClick={() => onReplaceHere(item.from, item.to)}
                    title={`Заменить первой буквы ${item.from} на ${item.to}`}
                  >
                    Заменить в слове
                  </Button>
                )}
                {onReplaceAll && (
                  <Button
                    variant="quiet"
                    onClick={() => onReplaceAll(item.from, item.to)}
                    title={`Заменить все ${item.from} на ${item.to} во всём тексте`}
                  >
                    Заменить везде
                  </Button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
