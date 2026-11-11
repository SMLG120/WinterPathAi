import { useTranslation } from 'react-i18next';
import { Monitor, Moon, Sun } from 'lucide-react';
import { useThemeStore, type ThemePref } from '@/stores/theme';
import { cn } from '@/lib/utils';

const OPTIONS: Array<{ v: ThemePref; Icon: typeof Sun }> = [
  { v: 'light', Icon: Sun },
  { v: 'dark', Icon: Moon },
  { v: 'system', Icon: Monitor },
];

export function ThemeToggle({ className }: { className?: string }) {
  const { t } = useTranslation('common');
  const { pref, setPref } = useThemeStore();
  return (
    <div role="group" aria-label={t('theme.label')} className={cn('inline-flex rounded-md border border-border p-0.5', className)}>
      {OPTIONS.map(({ v, Icon }) => (
        <button
          key={v}
          type="button"
          aria-pressed={pref === v}
          onClick={() => setPref(v)}
          className={cn(
            'inline-flex size-8 items-center justify-center rounded-sm text-muted-foreground hover:text-foreground',
            pref === v && 'bg-muted text-foreground',
          )}
        >
          <Icon className="size-4" aria-hidden="true" />
          <span className="sr-only">{t(`theme.${v}`)}</span>
        </button>
      ))}
    </div>
  );
}
