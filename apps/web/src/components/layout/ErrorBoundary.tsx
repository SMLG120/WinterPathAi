import { Component, type ReactNode } from 'react';
import { Translation } from 'react-i18next';
import { Button } from '@/components/ui/button';

export class ErrorBoundary extends Component<{ children: ReactNode; fallback?: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: unknown) {
    console.error('UI error boundary', error instanceof Error ? error.message : 'unknown');
  }
  render() {
    if (!this.state.failed) return this.props.children;
    if (this.props.fallback !== undefined) return this.props.fallback;
    return (
      <Translation ns="errors">
        {(t) => (
          <div role="alert" className="mx-auto max-w-xl space-y-3 px-4 py-16 text-center">
            <h1 className="text-xl font-semibold">{t('boundary.title')}</h1>
            <Button onClick={() => window.location.reload()}>{t('boundary.reload')}</Button>
          </div>
        )}
      </Translation>
    );
  }
}
