import { useQuery, useQueryClient } from "@tanstack/react-query";
import ActionButton from "../components/ActionButton";
import { api } from "../lib/api";

interface VoiceCheck {
  ok?: boolean;
  at?: string;
  latency_ms?: number;
  error?: string;
}

interface VoiceStatus {
  enabled: boolean;
  api_base: string | null;
  model: string;
  language: string;
  queue: number;
  last_check: VoiceCheck;
}

/** Голосовые реплики: сервер расшифровки на машине с игрой. Адрес и модель — в окружении сервера. */
export default function VoiceSection() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["admin-voice"], queryFn: () => api<VoiceStatus>("/api/admin/voice") });
  const s = status.data;
  const c = s?.last_check;

  return (
    <section className="card flex flex-col gap-4 border border-line bg-surface p-5 sm:p-6" aria-label="Голосовые реплики">
      <div>
        <h2 className="font-heading text-xl font-bold tracking-wide text-ink sm:text-2xl">Голосовые реплики</h2>
        <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted">
          Игроки записывают голосовое прямо в чат. Запись хранится на сервере, текст из неё делает локальная модель
          Whisper на этой же машине — звук в облако не уходит. Мастер работает с расшифровкой, игроки слышат голос.
        </p>
      </div>
      {status.isError && <p className="text-sm text-bad">{String(status.error.message)}</p>}
      {s && !s.enabled && (
        <div className="rounded-lg border border-warn/40 bg-warn/5 p-4 text-sm">
          <p className="font-semibold text-warn">Выключено: не задан адрес сервера расшифровки.</p>
          <p className="mt-1 text-muted">
            Запустите игру вместе с сервером расшифровки: <code className="font-mono">docker compose --profile voice up</code>{" "}
            и задайте в <code className="font-mono">.env</code> строку{" "}
            <code className="font-mono">STT_API_BASE=http://stt:8000/v1</code>. После перезапуска у поля ввода появится
            кнопка микрофона.
          </p>
        </div>
      )}
      {s?.enabled && (
        <>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs text-muted">Адрес (STT_API_BASE)</dt>
              <dd className="font-mono">{s.api_base}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Модель (STT_MODEL)</dt>
              <dd className="font-mono">{s.model}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Язык</dt>
              <dd className="font-mono">{s.language || "авто"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">В очереди сейчас</dt>
              <dd className="font-mono">{s.queue}</dd>
            </div>
          </dl>
          <div className="flex flex-wrap items-center gap-3">
            <ActionButton
              className="btn-outline-copper"
              run={async () => {
                await api<VoiceCheck>("/api/admin/voice/check", { method: "POST", body: {} });
                await qc.invalidateQueries({ queryKey: ["admin-voice"] });
              }}
            >
              Проверить
            </ActionButton>
            {c?.at &&
              (c.ok ? (
                <span className="font-mono text-xs text-patina-hi">
                  ✓ отвечает · секунда тишины за {c.latency_ms} мс
                </span>
              ) : (
                <span className="font-mono text-xs text-bad">✗ {c.error}</span>
              ))}
          </div>
          <p className="text-xs text-muted">
            Первая проверка после запуска дольше: сервер загружает модель в память. Записи расшифровываются по одной, остальные ждут
            в очереди.
          </p>
        </>
      )}
    </section>
  );
}
