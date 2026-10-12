import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { ApplicationAudioCoordinator, audioSurfaceFor, installAutoUnlock, installVisibilityListener } from "./applicationAudioCoordinator";
import { DEFAULT_MENU_MUSIC, useMenuMusicPreferences } from "./menuMusicPreferences";
import { useSession } from "../stores/session";
import { sound } from "../game/sound";

/** Координатор звука без собственного UI: живёт внутри BrowserRouter один раз. */
export default function ApplicationAudio() {
  const location = useLocation();
  const user = useSession((s) => s.user);
  const prefs = useMenuMusicPreferences((s) => s.prefs);
  const coordinator = useRef<ApplicationAudioCoordinator | null>(null);
  if (!coordinator.current) coordinator.current = new ApplicationAudioCoordinator();

  useEffect(() => {
    void coordinator.current!.reconcile(location.pathname, user, prefs);
  }, [location.pathname, user, prefs]);

  useEffect(() => installVisibilityListener(sound), []);

  useEffect(() => {
    return installAutoUnlock(
      sound,
      () => Boolean(prefs.enabled && prefs.volume > 0 && audioSurfaceFor(location.pathname, Boolean(user)) === "menu"),
    );
  }, [user, prefs.enabled, prefs.volume, location.pathname]);

  useEffect(() => () => { void coordinator.current?.reconcile("/", null, DEFAULT_MENU_MUSIC); }, []);
  return null;
}
