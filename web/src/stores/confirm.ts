// Одно общее окно подтверждения на приложение: действие запускается только после явного согласия.
import { create } from "zustand";

export interface ConfirmSpec {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Опасное действие: кнопка подтверждения красная. */
  danger?: boolean;
  /** Операция выполняется внутри окна: пока идёт — кнопки заняты, ошибка остаётся в окне. */
  run?: () => Promise<unknown>;
}

interface ConfirmState {
  spec: ConfirmSpec | null;
  busy: boolean;
  error: string | null;
  accept(): Promise<void>;
  cancel(): void;
}

let settle: ((accepted: boolean) => void) | null = null;

export const useConfirm = create<ConfirmState>((set, get) => ({
  spec: null,
  busy: false,
  error: null,
  async accept() {
    const { spec, busy } = get();
    if (!spec || busy) return;
    if (spec.run) {
      set({ busy: true, error: null });
      try {
        await spec.run();
      } catch (e) {
        set({ busy: false, error: e instanceof Error ? e.message : String(e) });
        return;
      }
    }
    set({ spec: null, busy: false, error: null });
    settle?.(true);
    settle = null;
  },
  cancel() {
    if (get().busy || !get().spec) return;
    set({ spec: null, error: null });
    settle?.(false);
    settle = null;
  },
}));

/** Открывает окно и ждёт ответа. Пока одно окно открыто, второй вызов ничего не запускает и отвечает «нет». */
export function confirmAction(spec: ConfirmSpec): Promise<boolean> {
  if (useConfirm.getState().spec) return Promise.resolve(false);
  return new Promise((resolve) => {
    settle = resolve;
    useConfirm.setState({ spec, busy: false, error: null });
  });
}

/** Старые подтверждения-строки: «Удалить X? Что станет с остальным.» → заголовок, описание и кнопка-глагол. */
export function specFromText(text: string): ConfirmSpec {
  const cut = text.search(/[?]\s/);
  const title = cut < 0 ? text : text.slice(0, cut + 1);
  const description = cut < 0 ? undefined : text.slice(cut + 1).trim() || undefined;
  const verb = title.split(/\s+/)[0] ?? "";
  return { title, description, confirmLabel: /^[А-ЯЁ][а-яё]+ть$/.test(verb) ? verb : undefined, danger: /^(Удалить|Убрать)$/.test(verb) };
}
