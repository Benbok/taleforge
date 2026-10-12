/** Музыку декодирует аудиоэлемент по мере проигрывания: десятиминутный MP3 не становится огромным AudioBuffer.
 * Файл получаем с Bearer-авторизацией; blob хранит сжатые байты только пока дорожка играет. */
export interface PreparedMusic {
  element: HTMLAudioElement;
  source: MediaElementAudioSourceNode;
  gain: GainNode;
  dispose(): void;
}

export interface MusicDeck {
  element: HTMLAudioElement;
  source: MediaElementAudioSourceNode;
}

/** Safari разрешает autoplay для конкретного элемента. Оба элемента запускаются прямо в обработчике клика
 * и затем переиспользуются при автоматической смене музыки. SourceNode создаётся один раз на элемент. */
export function primeMusic(ctx: AudioContext): { decks: MusicDeck[]; ready: Promise<void> } {
  // 100 мс тишины, mono PCM 8-bit / 8000 Hz, с полноценным WAV-заголовком.
  const wav = new Uint8Array(44 + 800);
  const header = new DataView(wav.buffer);
  for (const [offset, text] of [[0, "RIFF"], [8, "WAVE"], [12, "fmt "], [36, "data"]] as const) {
    for (let i = 0; i < text.length; i++) wav[offset + i] = text.charCodeAt(i);
  }
  header.setUint32(4, wav.length - 8, true);
  header.setUint32(16, 16, true);
  header.setUint16(20, 1, true);
  header.setUint16(22, 1, true);
  header.setUint32(24, 8000, true);
  header.setUint32(28, 8000, true);
  header.setUint16(32, 1, true);
  header.setUint16(34, 8, true);
  header.setUint32(40, 800, true);
  wav.fill(128, 44);
  const silence = `data:audio/wav;base64,${btoa(String.fromCharCode(...wav))}`;
  const decks = Array.from({ length: 2 }, () => {
    const element = new Audio();
    element.src = silence;
    return { element, source: ctx.createMediaElementSource(element) };
  });
  const ready = Promise.all(decks.map(({ element }) => element.play())).then(() => {
    for (const { element } of decks) {
      element.pause();
      element.removeAttribute("src");
      element.load();
    }
  });
  return { decks, ready };
}

export async function prepareMusic(
  ctx: AudioContext, url: string, token: string, signal: AbortSignal, deck?: MusicDeck,
): Promise<PreparedMusic> {
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` }, signal });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `ошибка сервера (${res.status})`);
  }
  const blob = await res.blob();
  signal.throwIfAborted();
  const element = deck?.element ?? new Audio();
  const objectUrl = URL.createObjectURL(blob);
  let source: MediaElementAudioSourceNode | undefined;
  let gain: GainNode | undefined;
  let disposed = false;
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    signal.removeEventListener("abort", dispose);
    element.pause();
    element.removeAttribute("src");
    element.load();
    source?.disconnect();
    gain?.disconnect();
    URL.revokeObjectURL(objectUrl);
  };
  signal.addEventListener("abort", dispose, { once: true });
  try {
    element.preload = "auto";
    element.loop = true;
    source = deck?.source ?? ctx.createMediaElementSource(element);
    gain = ctx.createGain();
    source.connect(gain);
    await new Promise<void>((resolve, reject) => {
      const cleanup = () => {
        clearTimeout(timeout);
        element.removeEventListener("loadedmetadata", loaded);
        element.removeEventListener("error", failed);
        signal.removeEventListener("abort", aborted);
      };
      const loaded = () => { cleanup(); resolve(); };
      const failed = () => { cleanup(); reject(new Error("браузер не прочитал аудио")); };
      const aborted = () => { cleanup(); reject(signal.reason); };
      const timeout = setTimeout(failed, 30_000);
      element.addEventListener("loadedmetadata", loaded, { once: true });
      element.addEventListener("error", failed, { once: true });
      signal.addEventListener("abort", aborted, { once: true });
      element.src = objectUrl;
      element.load();
    });
    signal.throwIfAborted();
    return { element, source, gain, dispose };
  } catch (e) {
    dispose();
    throw e;
  }
}
