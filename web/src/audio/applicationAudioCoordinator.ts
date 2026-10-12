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

export function audioSurfaceFor(pathname: string, signedIn: boolean): AudioSurface {
  if (!signedIn) return "silent";
  const path = pathname.split(/[?#]/, 1)[0] || "/";
  if (path === "/" || path === "/new" || path === "/profile"
    || /^\/heroes\/[^/]+$/.test(path)
    || /^\/c\/[^/]+\/(manage|hero)$/.test(path)) return "menu";
  if (/^\/c\/[^/]+$/.test(path)) return "scene";
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
    if (!user) {
      this.generation++;
      this.userId = null;
      this.theme = undefined;
      this.themeRequest = null;
      this.mixer.stop();
      return;
    }
    if (this.userId !== user.id) {
      if (this.userId !== null) this.mixer.stop();
      this.generation++;
      this.userId = user.id;
      this.theme = undefined;
      this.themeRequest = null;
    }
    const mine = this.generation;
    const surface = audioSurfaceFor(pathname, true);
    await this.mixer.setSurface(surface);
    if (mine !== this.generation || this.userId !== user.id || reconcileGeneration !== this.reconcileGeneration) return;
    if (this.theme === undefined) {
      this.themeRequest ??= api<AudioTrack | null>("/api/menu-music").catch(() => null);
      const theme = await this.themeRequest;
      if (mine !== this.generation || this.userId !== user.id || reconcileGeneration !== this.reconcileGeneration) return;
      this.theme = theme;
    }
    if (mine !== this.generation || this.userId !== user.id || reconcileGeneration !== this.reconcileGeneration) return;
    await this.mixer.setMenuMusic(surface === "menu" ? this.theme ?? null : null, prefs);
  }

  invalidate() {
    this.generation++;
    this.userId = null;
    this.theme = undefined;
    this.themeRequest = null;
  }
}
