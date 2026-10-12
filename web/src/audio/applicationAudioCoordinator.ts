import { api } from "../lib/api";
import type { AudioSurface, MenuMusicPreferences, SoundMixer } from "../game/sound";
import { sound } from "../game/sound";
import type { AudioTrack, User } from "../lib/types";

export function installVisibilityListener(
  mixer: Pick<SoundMixer, "setDocumentVisible">,
): () => void {
  const onVisibilityChange = () => {
    void mixer.setDocumentVisible(document.visibilityState === "visible");
  };
  document.addEventListener("visibilitychange", onVisibilityChange);
  onVisibilityChange();
  return () => document.removeEventListener("visibilitychange", onVisibilityChange);
}

export function installAutoUnlock(
  mixer: Pick<SoundMixer, "unlock"> & { unlocked: boolean },
  shouldUnlock: () => boolean,
): () => void {
  const tryUnlock = () => {
    if (!mixer.unlocked && shouldUnlock()) {
      void mixer.unlock().catch(() => {});
    }
  };
  tryUnlock();
  const onInteraction = () => {
    tryUnlock();
  };
  window.addEventListener("pointerdown", onInteraction, { passive: true });
  window.addEventListener("keydown", onInteraction, { passive: true });
  return () => {
    window.removeEventListener("pointerdown", onInteraction);
    window.removeEventListener("keydown", onInteraction);
  };
}

export function audioSurfaceFor(pathname: string, signedIn: boolean): AudioSurface {
  const path = pathname.split(/[?#]/, 1)[0] || "/";
  if (/^\/c\/[^/]+$/.test(path)) return signedIn ? "scene" : "silent";
  if (path === "/" || path === "/admin" || path === "/new" || path === "/profile"
    || /^\/worlds(\/[^/]+)?$/.test(path)
    || /^\/heroes\/[^/]+$/.test(path)
    || /^\/c\/[^/]+\/(manage|hero)$/.test(path)) return "menu";
  return "silent";
}

export class ApplicationAudioCoordinator {
  private generation = 0;
  private reconcileGeneration = 0;
  private userId: string | null = null;
  private theme: AudioTrack | null | undefined;
  private themeRequest: Promise<AudioTrack | null> | null = null;

  constructor(private readonly mixer: Pick<SoundMixer, "setSurface" | "setMenuMusic" | "stop"> = sound) {}

  async reconcile(pathname: string, user: User | null, prefs: MenuMusicPreferences): Promise<void> {
    const reconcileGeneration = ++this.reconcileGeneration;
    const nextUserId = user ? user.id : null;
    if (this.userId !== nextUserId) {
      if (this.userId !== null) this.mixer.stop();
      this.generation++;
      this.userId = nextUserId;
      this.theme = undefined;
      this.themeRequest = null;
    }
    const mine = this.generation;
    const surface = audioSurfaceFor(pathname, Boolean(user));
    await this.mixer.setSurface(surface);
    if (mine !== this.generation || this.userId !== nextUserId || reconcileGeneration !== this.reconcileGeneration) return;
    if (surface === "silent") {
      return;
    }
    if (this.theme === undefined) {
      this.themeRequest ??= api<AudioTrack | null>("/api/menu-music").catch(() => null);
      const theme = await this.themeRequest;
      if (mine !== this.generation || this.userId !== nextUserId || reconcileGeneration !== this.reconcileGeneration) return;
      this.theme = theme;
    }
    if (mine !== this.generation || this.userId !== nextUserId || reconcileGeneration !== this.reconcileGeneration) return;
    await this.mixer.setMenuMusic(surface === "menu" ? this.theme ?? null : null, prefs);
  }

  invalidate() {
    this.generation++;
    this.userId = null;
    this.theme = undefined;
    this.themeRequest = null;
  }
}
