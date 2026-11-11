import { useEffect } from 'react';
import { resolveTheme, useThemeStore } from '@/stores/theme';

export function useApplyTheme() {
  const pref = useThemeStore((s) => s.pref);
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
    const apply = () => {
      const theme = resolveTheme(pref, mq?.matches ?? false);
      document.documentElement.classList.toggle('dark', theme === 'dark');
      document.documentElement.dataset.theme = theme;
    };
    apply();
    mq?.addEventListener?.('change', apply);
    return () => mq?.removeEventListener?.('change', apply);
  }, [pref]);
}
