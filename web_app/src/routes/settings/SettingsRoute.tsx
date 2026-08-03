import { useEffect, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'motion/react';

import { useAccess } from '@shared/access/AccessProvider';
import { useNetworkStatus } from '@shared/lib/useNetworkStatus';
import { motionTransition, useAccessibleMotion } from '@shared/motion';
import { ThemeToggle } from '@shared/theme';
import { Button, Icon, Status } from '@shared/ui';

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
type SettingsTab = 'account' | 'appearance' | 'recognition' | 'storage' | 'security';

function loadSettings(): HtrSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    return raw ? { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } : DEFAULT_SETTINGS;
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function calculateStorageUsage(): string {
  try {
    let totalBytes = 0;
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (key) totalBytes += (key.length + (localStorage.getItem(key)?.length ?? 0)) * 2;
    }
    if (totalBytes < 1024) return `${totalBytes} Б`;
    if (totalBytes < 1024 * 1024) return `${(totalBytes / 1024).toFixed(1)} КБ`;
    return `${(totalBytes / (1024 * 1024)).toFixed(2)} МБ`;
  } catch {
    return '0 КБ';
  }
}

function SettingRow({
  label,
  description,
  children,
}: Readonly<{ label: string; description?: string; children: ReactNode }>) {
  return (
    <div className="new-setting-row">
      <div>
        <strong>{label}</strong>
        {description ? <p>{description}</p> : null}
      </div>
      <div>{children}</div>
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
}: Readonly<{ checked: boolean; onChange: (value: boolean) => void; label: string }>) {
  return (
    <button
      className="new-toggle"
      type="button"
      role="switch"
      aria-label={label}
      aria-checked={checked}
      onClick={() => onChange(!checked)}
    >
      <span />
    </button>
  );
}

const tabs: ReadonlyArray<{
  id: SettingsTab;
  label: string;
  icon: 'home' | 'settings' | 'scan' | 'document' | 'shield';
}> = [
  { id: 'account', label: 'Аккаунт', icon: 'home' },
  { id: 'appearance', label: 'Интерфейс', icon: 'settings' },
  { id: 'recognition', label: 'Распознавание', icon: 'scan' },
  { id: 'storage', label: 'Хранилище', icon: 'document' },
  { id: 'security', label: 'Безопасность', icon: 'shield' },
];

export default function SettingsRoute() {
  const access = useAccess();
  const navigate = useNavigate();
  const isOnline = useNetworkStatus();
  const canAnimate = useAccessibleMotion();
  const [activeTab, setActiveTab] = useState<SettingsTab>('account');
  const [settings, setSettings] = useState<HtrSettings>(loadSettings);
  const [storageSize, setStorageSize] = useState(calculateStorageUsage);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.dataset.fontSize = settings.fontSize;
    if (settings.highContrast) document.documentElement.dataset.highContrast = 'true';
    else delete document.documentElement.dataset.highContrast;
  }, [settings]);

  function updateSetting<K extends keyof HtrSettings>(key: K, value: HtrSettings[K]) {
    const next = { ...settings, [key]: value };
    setSettings(next);
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(next));
      setStorageSize(calculateStorageUsage());
    } catch {
      setNotice('Настройка действует до закрытия этой вкладки.');
    }
  }

  function clearLocalCache() {
    try {
      const keys: string[] = [];
      for (let index = 0; index < localStorage.length; index += 1) {
        const key = localStorage.key(index);
        if (key && key !== SETTINGS_KEY && key !== 'tajik-htr-theme') keys.push(key);
      }
      keys.forEach((key) => localStorage.removeItem(key));
      setStorageSize(calculateStorageUsage());
      setNotice('Локальный кэш очищен.');
    } catch {
      setNotice('Не удалось очистить локальный кэш.');
    }
  }

  async function logout() {
    await access.logout();
    navigate('/access', { replace: true });
  }

  return (
    <section className="new-settings" aria-labelledby="settings-title">
      <header>
        <h1 id="settings-title">Настройки</h1>
        <p>Управляйте аккаунтом и поведением рабочего пространства.</p>
      </header>

      <div className="new-settings__layout">
        <nav className="new-settings__tabs" aria-label="Разделы настроек">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={activeTab === tab.id ? 'is-active' : ''}
              aria-current={activeTab === tab.id ? 'page' : undefined}
              onClick={() => setActiveTab(tab.id)}
            >
              <Icon name={tab.icon} />
              {tab.label}
            </button>
          ))}
        </nav>

        <motion.section
          key={activeTab}
          className="new-settings__panel"
          initial={canAnimate ? { opacity: 0, y: 10 } : false}
          animate={{ opacity: 1, y: 0 }}
          transition={motionTransition.enter}
        >
          {activeTab === 'account' ? (
            <>
              <div className="new-settings__panel-heading">
                <h2>Аккаунт</h2>
                <p>Личные данные, связанные с документами.</p>
              </div>
              <SettingRow label="Имя" description="Отображается в вашем рабочем пространстве.">
                <span>{access.user?.name || '—'}</span>
              </SettingRow>
              <SettingRow label="Электронная почта">
                <span>{access.user?.email || '—'}</span>
              </SettingRow>
              <div className="new-settings__danger">
                <div>
                  <strong>Выйти из аккаунта</strong>
                  <p>Локальные несохранённые изменения могут быть потеряны.</p>
                </div>
                <Button variant="secondary" onClick={() => void logout()}>
                  Выйти
                </Button>
              </div>
            </>
          ) : null}

          {activeTab === 'appearance' ? (
            <>
              <div className="new-settings__panel-heading">
                <h2>Интерфейс</h2>
                <p>Тема и параметры чтения.</p>
              </div>
              <SettingRow label="Тема оформления" description="Светлая, тёмная или системная.">
                <ThemeToggle />
              </SettingRow>
              <SettingRow label="Крупный текст">
                <Toggle
                  label="Крупный текст"
                  checked={settings.fontSize === 'large'}
                  onChange={(checked) =>
                    updateSetting('fontSize', checked ? 'large' : 'normal')
                  }
                />
              </SettingRow>
              <SettingRow label="Высокая контрастность">
                <Toggle
                  label="Высокая контрастность"
                  checked={settings.highContrast}
                  onChange={(checked) => updateSetting('highContrast', checked)}
                />
              </SettingRow>
            </>
          ) : null}

          {activeTab === 'recognition' ? (
            <>
              <div className="new-settings__panel-heading">
                <h2>Распознавание</h2>
                <p>Параметры проверки текста после модели.</p>
              </div>
              <SettingRow
                label="Автозамена таджикских букв"
                description="Нормализовать типичные варианты символов в редакторе."
              >
                <Toggle
                  label="Автозамена таджикских букв"
                  checked={settings.autoReplaceTajik}
                  onChange={(checked) => updateSetting('autoReplaceTajik', checked)}
                />
              </SettingRow>
              <SettingRow label="Язык по умолчанию">
                <select
                  className="new-settings__select"
                  value={settings.defaultLanguage}
                  onChange={(event) => updateSetting('defaultLanguage', event.target.value)}
                >
                  <option value="tgk_cyrillic">Таджикский</option>
                  <option value="rus">Русский</option>
                  <option value="eng">Английский</option>
                </select>
              </SettingRow>
              <SettingRow
                label={`Порог уверенности: ${settings.confidenceThreshold}%`}
                description="Строки ниже порога будут отмечены для ручной проверки."
              >
                <input
                  type="range"
                  min="50"
                  max="98"
                  value={settings.confidenceThreshold}
                  onChange={(event) =>
                    updateSetting('confidenceThreshold', Number(event.target.value))
                  }
                />
              </SettingRow>
            </>
          ) : null}

          {activeTab === 'storage' ? (
            <>
              <div className="new-settings__panel-heading">
                <h2>Хранилище</h2>
                <p>Локальные настройки и временные данные браузера.</p>
              </div>
              <SettingRow label="Использовано локально">
                <span>{storageSize}</span>
              </SettingRow>
              <SettingRow label="Очистить временные данные">
                <Button variant="secondary" onClick={clearLocalCache}>
                  Очистить кэш
                </Button>
              </SettingRow>
            </>
          ) : null}

          {activeTab === 'security' ? (
            <>
              <div className="new-settings__panel-heading">
                <h2>Безопасность</h2>
                <p>Состояние текущего соединения и аккаунта.</p>
              </div>
              <SettingRow label="Соединение с API">
                <Status tone={isOnline ? 'success' : 'warning'}>
                  {isOnline ? 'Сервер на связи' : 'Нет подключения'}
                </Status>
              </SettingRow>
              <SettingRow label="Срок текущей сессии">
                <span>
                  {access.expiresAt
                    ? new Date(access.expiresAt).toLocaleString('ru-RU')
                    : 'Уточняется'}
                </span>
              </SettingRow>
            </>
          ) : null}

          {notice ? <Status tone="info">{notice}</Status> : null}
        </motion.section>
      </div>
    </section>
  );
}
