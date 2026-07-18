import { useId, type ReactNode } from 'react';

export type TabItem = Readonly<{ id: string; label: string; panel: ReactNode }>;

export function Tabs({
  items,
  activeId,
  onChange,
}: Readonly<{ items: readonly TabItem[]; activeId: string; onChange: (id: string) => void }>) {
  const labelId = useId();
  const active = items.find((item) => item.id === activeId) ?? items[0];
  if (!active) return null;
  return (
    <div>
      <div className="ui-tabs" role="tablist" aria-labelledby={labelId}>
        <span id={labelId} className="visually-hidden">
          Вкладки
        </span>
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={item.id === active.id}
            aria-controls={`${item.id}-panel`}
            id={`${item.id}-tab`}
            onClick={() => onChange(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div
        id={`${active.id}-panel`}
        role="tabpanel"
        aria-labelledby={`${active.id}-tab`}
        tabIndex={0}
      >
        {active.panel}
      </div>
    </div>
  );
}
