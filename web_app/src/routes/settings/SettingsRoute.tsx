import { useEffect, useState } from 'react';
import { motion } from 'motion/react';

import { useNetworkStatus } from '@shared/lib/useNetworkStatus';
import { fadeVariants, motionTransition, useAccessibleMotion } from '@shared/motion';
import { ThemeToggle } from '@shared/theme';
import { Badge, Button, Card, Icon, Status } from '@shared/ui';

export interface HtrSettings {
  fontSize: 'normal' | 'large';
  highContrast: boolean;
  autoReplaceTajik: boolean;
  defaultLanguage: string;
  confidenceThreshold: number;
  autosaveInterval: 3 | 5 | 10;
}

const DEFAULT_SETTINGS: HtrSettings = {
  fontSize: 'normal',
  highContrast: false,
  autoReplaceTajik: true,
  defaultLanguage: 'tgk_cyrillic',
  confidenceThreshold: 80,
  autosaveInterval: 5,
};

const SETTINGS_KEY = 'htr_settings';

function loadSettings(): HtrSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) {
      return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
    }
  } catch {
    // fallback to defaults if parse fails
  }
  return DEFAULT_SETTINGS;
}

function calculateStorageUsage(): string {
  try {
    let totalBytes = 0;
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key) {
        const val = localStorage.getItem(key) ?? '';
        totalBytes += (key.length + val.length) * 2;
      }
    }
    if (totalBytes < 1024) return `${totalBytes} Б`;
    if (totalBytes < 1024 * 1024) return `${(totalBytes / 1024).toFixed(1)} КБ`;
    return `${(totalBytes / (1024 * 1024)).toFixed(2)} МБ`;
  } catch {
    return '0 КБ';
  }
}

export default function SettingsRoute() {
  const canAnimate = useAccessibleMotion();
  const isOnline = useNetworkStatus();

  const [settings, setSettings] = useState<HtrSettings>(loadSettings);
  const [storageSize, setStorageSize] = useState<string>(calculateStorageUsage);
  const [clearStatus, setClearStatus] = useState<string | null>(null);

  useEffect(() => {
    if (settings.highContrast) {
      document.documentElement.dataset.highContrast = 'true';
    } else {
      delete document.documentElement.dataset.highContrast;
    }
    document.documentElement.dataset.fontSize = settings.fontSize;
  }, [settings]);

  const updateSetting = <K extends keyof HtrSettings>(key: K, value: HtrSettings[K]) => {
    const nextSettings = { ...settings, [key]: value };
    setSettings(nextSettings);
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(nextSettings));
      setStorageSize(calculateStorageUsage());
    } catch {
      // The in-memory preference remains active when browser storage is unavailable.
    }
  };

  const handleClearCache = () => {
    try {
      const keysToRemove: string[] = [];
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && key !== SETTINGS_KEY && key !== 'tajik-htr-theme') {
          keysToRemove.push(key);
        }
      }
      keysToRemove.forEach((k) => localStorage.removeItem(k));
      setStorageSize(calculateStorageUsage());
      setClearStatus('Локальный кэш и черновики очищены.');
    } catch {
      setClearStatus('Ошибка при очистке локального кэша.');
    }
  };

  return (
    <section className="settings-page" aria-labelledby="settings-title">
      <motion.div
        className="settings-page__header"
        initial={canAnimate ? 'hidden' : false}
        animate="visible"
        variants={fadeVariants}
        transition={motionTransition.enter}
      >
        <div className="settings-page__title-wrap">
          <Badge tone="info">Параметры и конфигурация</Badge>
          <p className="eyebrow">Конфигурация Tajik HTR Studio</p>
          <h1 id="settings-title">Настройки системы</h1>
        </div>
        <p className="settings-page__description">
          Персонализируйте внешний вид интерфейса, параметры модели распознавания рукописей и
          управление локальным хранилищем. Все параметры сохраняются мгновенно.
        </p>
      </motion.div>

      <div className="settings-page__grid">
        {/* Section 1: Внешний вид */}
        <motion.div
          initial={canAnimate ? { opacity: 0, y: 12 } : false}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...motionTransition.enter, delay: canAnimate ? 0.04 : 0 }}
        >
          <Card className="settings-card">
            <div className="settings-card__header">
              <div className="settings-card__icon-wrap">
                <Icon name="sparkles" />
              </div>
              <div>
                <p className="eyebrow">Интерфейс</p>
                <h2>Внешний вид</h2>
              </div>
            </div>

            <div className="settings-group">
              <div className="settings-item">
                <div className="settings-item__info">
                  <span className="settings-item__label">Тема оформления</span>
                  <span className="settings-item__hint">
                    Выбор между светлой, тёмной и системной темой
                  </span>
                </div>
                <div className="settings-item__control">
                  <ThemeToggle />
                </div>
              </div>

              <div className="settings-item">
                <div className="settings-item__info">
                  <span className="settings-item__label">Размер шрифта интерфейса</span>
                  <span className="settings-item__hint">
                    Масштабирование текста для удобства чтения
                  </span>
                </div>
                <div className="settings-item__control">
                  <div className="settings-segmented">
                    <button
                      type="button"
                      className={`settings-segmented__btn ${settings.fontSize === 'normal' ? 'settings-segmented__btn--active' : ''}`}
                      onClick={() => updateSetting('fontSize', 'normal')}
                    >
                      Обычный
                    </button>
                    <button
                      type="button"
                      className={`settings-segmented__btn ${settings.fontSize === 'large' ? 'settings-segmented__btn--active' : ''}`}
                      onClick={() => updateSetting('fontSize', 'large')}
                    >
                      Увеличенный
                    </button>
                  </div>
                </div>
              </div>

              <div className="settings-item">
                <div className="settings-item__info">
                  <label htmlFor="high-contrast-toggle" className="settings-item__label">
                    Высокая контрастность
                  </label>
                  <span className="settings-item__hint">
                    Повышенная четкость границ и графических элементов
                  </span>
                </div>
                <div className="settings-item__control">
                  <label className="settings-toggle" htmlFor="high-contrast-toggle">
                    <input
                      id="high-contrast-toggle"
                      type="checkbox"
                      checked={settings.highContrast}
                      onChange={(e) => updateSetting('highContrast', e.target.checked)}
                    />
                    <span className="settings-toggle__slider" />
                  </label>
                </div>
              </div>
            </div>
          </Card>
        </motion.div>

        {/* Section 2: Распознавание */}
        <motion.div
          initial={canAnimate ? { opacity: 0, y: 12 } : false}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...motionTransition.enter, delay: canAnimate ? 0.08 : 0 }}
        >
          <Card className="settings-card">
            <div className="settings-card__header">
              <div className="settings-card__icon-wrap">
                <Icon name="scan" />
              </div>
              <div>
                <p className="eyebrow">Модель HTR</p>
                <h2>Распознавание</h2>
              </div>
            </div>

            <div className="settings-group">
              <div className="settings-item">
                <div className="settings-item__info">
                  <span className="settings-item__label">Автозамена букв таджикского алфавита</span>
                  <span className="settings-item__hint">
                    Автоматическая нормализация символов: г→ғ, и→ӣ, к→қ, у→ӯ, х→ҳ, ч→ҷ
                  </span>
                </div>
                <div className="settings-item__control">
                  <label className="settings-toggle" htmlFor="auto-replace-tajik-toggle">
                    <input
                      id="auto-replace-tajik-toggle"
                      type="checkbox"
                      checked={settings.autoReplaceTajik}
                      onChange={(e) => updateSetting('autoReplaceTajik', e.target.checked)}
                    />
                    <span className="settings-toggle__slider" />
                  </label>
                </div>
              </div>

              <div className="settings-item">
                <div className="settings-item__info">
                  <span className="settings-item__label">Язык по умолчанию</span>
                  <span className="settings-item__hint">
                    Языковой профиль для первоначального распознавания
                  </span>
                </div>
                <div className="settings-item__control">
                  <select
                    className="settings-select"
                    value={settings.defaultLanguage}
                    onChange={(e) => updateSetting('defaultLanguage', e.target.value)}
                    aria-label="Язык по умолчанию"
                  >
                    <option value="tgk_cyrillic">Таджикский (кириллица)</option>
                    <option value="tgk_perso_arabic">Персидский (арабская вязь)</option>
                    <option value="rus">Русский</option>
                    <option value="eng">Английский</option>
                  </select>
                </div>
              </div>

              <div className="settings-item settings-item--vertical">
                <div className="settings-item__info">
                  <div className="settings-item__label-row">
                    <span className="settings-item__label">Порог уверенности (Confidence)</span>
                    <Badge tone="neutral">{settings.confidenceThreshold}%</Badge>
                  </div>
                  <span className="settings-item__hint">
                    Минимальный порог распознавания символов для автоматического принятия
                  </span>
                </div>
                <div className="settings-item__control settings-item__control--full">
                  <div className="settings-range-wrap">
                    <span className="settings-range-limit">50%</span>
                    <input
                      className="settings-range"
                      type="range"
                      min="50"
                      max="98"
                      step="1"
                      value={settings.confidenceThreshold}
                      onChange={(e) =>
                        updateSetting('confidenceThreshold', Number.parseInt(e.target.value, 10))
                      }
                      aria-label="Порог уверенности"
                    />
                    <span className="settings-range-limit">98%</span>
                  </div>
                </div>
              </div>
            </div>
          </Card>
        </motion.div>

        {/* Section 3: Хранилище */}
        <motion.div
          initial={canAnimate ? { opacity: 0, y: 12 } : false}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...motionTransition.enter, delay: canAnimate ? 0.12 : 0 }}
        >
          <Card className="settings-card">
            <div className="settings-card__header">
              <div className="settings-card__icon-wrap">
                <Icon name="document" />
              </div>
              <div>
                <p className="eyebrow">Данные</p>
                <h2>Хранилище</h2>
              </div>
            </div>

            <div className="settings-group">
              <div className="settings-item">
                <div className="settings-item__info">
                  <span className="settings-item__label">Использовано в localStorage</span>
                  <span className="settings-item__hint">
                    Размер сохранённых локальных настроек и кешированных черновиков
                  </span>
                </div>
                <div className="settings-item__control">
                  <Badge tone="info">{storageSize}</Badge>
                </div>
              </div>

              <div className="settings-item">
                <div className="settings-item__info">
                  <span className="settings-item__label">Интервал автосохранения</span>
                  <span className="settings-item__hint">
                    Периодичность фонового сохранения результатов работы
                  </span>
                </div>
                <div className="settings-item__control">
                  <div className="settings-segmented">
                    {([3, 5, 10] as const).map((interval) => (
                      <button
                        key={interval}
                        type="button"
                        className={`settings-segmented__btn ${settings.autosaveInterval === interval ? 'settings-segmented__btn--active' : ''}`}
                        onClick={() => updateSetting('autosaveInterval', interval)}
                      >
                        {interval}с
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="settings-item settings-item--vertical">
                <div className="settings-item__info">
                  <span className="settings-item__label">Очистка локального кэша</span>
                  <span className="settings-item__hint">
                    Удаление временных локальных черновиков и кешированных данных страниц
                  </span>
                </div>
                <div className="settings-item__control settings-item__control--action">
                  <Button type="button" className="ui-button--secondary" onClick={handleClearCache}>
                    Очистить локальный кэш
                  </Button>
                  {clearStatus ? <Status tone="success">{clearStatus}</Status> : null}
                </div>
              </div>
            </div>
          </Card>
        </motion.div>

        {/* Section 4: О приложении */}
        <motion.div
          initial={canAnimate ? { opacity: 0, y: 12 } : false}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...motionTransition.enter, delay: canAnimate ? 0.16 : 0 }}
        >
          <Card className="settings-card">
            <div className="settings-card__header">
              <div className="settings-card__icon-wrap">
                <Icon name="shield" />
              </div>
              <div>
                <p className="eyebrow">Информация</p>
                <h2>О приложении</h2>
              </div>
            </div>

            <div className="settings-group">
              <div className="settings-item">
                <div className="settings-item__info">
                  <span className="settings-item__label">Версия приложения</span>
                  <span className="settings-item__hint">Tajik HTR Studio Web Release</span>
                </div>
                <div className="settings-item__control">
                  <Badge tone="success">Tajik HTR Studio v1.0.0</Badge>
                </div>
              </div>

              <div className="settings-item">
                <div className="settings-item__info">
                  <span className="settings-item__label">Серверное соединение</span>
                  <span className="settings-item__hint">Текущее состояние подключения к API</span>
                </div>
                <div className="settings-item__control">
                  <Status tone={isOnline ? 'success' : 'warning'}>
                    {isOnline ? 'Сервер на связи (онлайн)' : 'Автономный режим (офлайн)'}
                  </Status>
                </div>
              </div>

              <div className="settings-item settings-item--vertical">
                <div className="settings-item__info">
                  <span className="settings-item__label">
                    Конфиденциальность и локальная обработка
                  </span>
                  <p className="settings-privacy-text">
                    Все изображения, макеты страниц и распознанный текст обрабатываются локально на
                    вашем сервере или устройстве. Ваши конфиденциальные данные и рукописные
                    документы не передаются сторонним облачным сервисам.
                  </p>
                </div>
              </div>
            </div>
          </Card>
        </motion.div>
      </div>
    </section>
  );
}
