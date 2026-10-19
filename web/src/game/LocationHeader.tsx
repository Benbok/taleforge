import { useState, type MouseEvent } from "react";
import type { Scene } from "../lib/types";
import { useInspector } from "./inspector";
import { loadSceneHeaderCollapsed, saveSceneHeaderCollapsed } from "./scenePreferences";
import { presentationSubtitle } from "./scenePresentation";
import SceneArtwork from "./SceneArtwork";

export default function LocationHeader({ scene }: { scene: Scene | null }) {
  const open = useInspector((s) => s.open);
  const [collapsed, setCollapsed] = useState(loadSceneHeaderCollapsed);
  const location = scene?.location;
  const subtitle = presentationSubtitle(scene?.presentation);
  const toggle = () => {
    setCollapsed((value) => {
      const next = !value;
      saveSceneHeaderCollapsed(next);
      return next;
    });
  };
  return (
    <section className={`tf-location-header ${collapsed ? "is-collapsed" : ""} ${scene?.mode === "combat" ? "is-combat" : ""}`} aria-label="Текущая локация">
      <SceneArtwork presentation={scene?.presentation} />
      <div className="tf-location-header__veil" />
      <div className="tf-location-header__body">
        <div className="tf-location-header__main">
          <div className="tf-location-header__kicker">
            <span className="tf-location-header__pin" aria-hidden="true">⌖</span>
            <span>Текущее место</span>
          </div>
          <div className="tf-location-header__row">
            {location ? (
              <button
                type="button"
                className="tf-location-header__name"
                title={`Осмотреть: ${location.name}`}
                onClick={(event: MouseEvent<HTMLButtonElement>) => open(location.id, location.name, event.currentTarget)}
              >
                <span className="tf-location-header__title">{location.name}</span>
                <span className="tf-location-header__info-badge" aria-hidden="true">ⓘ</span>
              </button>
            ) : (
              <p className="tf-location-header__name tf-location-header__name--empty">Место ещё не названо</p>
            )}
            {subtitle && <span className="tf-location-header__subtitle">{subtitle}</span>}
          </div>
        </div>
        <button
          type="button"
          className="tf-location-header__toggle"
          aria-expanded={!collapsed}
          aria-label={collapsed ? "Развернуть шапку" : "Свернуть шапку"}
          title={collapsed ? "Развернуть шапку локации" : "Свернуть шапку локации"}
          onClick={toggle}
        >
          <span className="tf-location-header__toggle-icon" aria-hidden="true">
            {collapsed ? "▼" : "▲"}
          </span>
        </button>
      </div>
    </section>
  );
}
