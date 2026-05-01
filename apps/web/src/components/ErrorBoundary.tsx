'use client';

import { Component, ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  name?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error(`[ErrorBoundary:${this.props.name || 'unnamed'}]`, error, info);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-6 text-center" role="alert">
          <AlertTriangle className="w-8 h-8 text-red-400 mx-auto mb-3" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-red-300 mb-1">
            {this.props.name ? `${this.props.name} failed to load` : 'Something went wrong'}
          </h3>
          <p className="text-xs text-slate-400 mb-4 max-w-xs mx-auto break-words">
            {this.state.error?.message?.slice(0, 150)}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-700/50 border border-slate-600 text-xs text-slate-300 hover:bg-slate-700 transition-colors"
            aria-label="Retry loading this section"
          >
            <RefreshCw className="w-3 h-3" aria-hidden="true" />
            Retry
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
