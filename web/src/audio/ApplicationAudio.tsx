import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { ApplicationAudioCoordinator } from "./applicationAudioCoordinator";
import { DEFAULT_MENU_MUSIC, useMenuMusicPreferences } from "./menuMusicPreferences";
import { useSession } from "../stores/session";

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

  useEffect(() => () => { void coordinator.current?.reconcile("/", null, DEFAULT_MENU_MUSIC); }, []);
  return null;
}
