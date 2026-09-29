import { Component, type ErrorInfo, type ReactNode } from "react";

/** Ловит падение отрисовки: вместо чёрного экрана — причина и выход. «Попробовать снова» перерисовывает
 *  приложение без перезагрузки страницы, «Обновить страницу» — полная перезагрузка. */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Ошибка отрисовки:", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="flex min-h-dvh items-center justify-center bg-bg p-4 text-ink">
        <div role="alert" className="card flex w-full max-w-lg flex-col gap-3 border-bad/40 p-5">
          <h1 className="font-heading text-xl font-bold">Что-то сломалось в интерфейсе</h1>
          <p className="text-sm text-muted">
            Игра на сервере продолжается. Попробуйте перерисовать окно; если ошибка повторится — обновите страницу и
            перешлите текст ниже разработчику.
          </p>
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-raised p-2 font-mono text-xs text-bad">
            {error.message}
          </pre>
          <div className="flex flex-wrap gap-2">
            <button className="btn btn-primary px-3 py-1.5 text-sm" onClick={() => this.setState({ error: null })}>
              Попробовать снова
            </button>
            <button className="btn px-3 py-1.5 text-sm" onClick={() => window.location.reload()}>
              Обновить страницу
            </button>
          </div>
        </div>
      </div>
    );
  }
}
