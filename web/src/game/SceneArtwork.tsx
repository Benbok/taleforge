import { useEffect, useState } from "react";
import type { LocationPresentation } from "../lib/types";
import { resolveSceneArt } from "./scenePresentation";

export default function SceneArtwork({ presentation }: { presentation: LocationPresentation | null | undefined }) {
  const art = resolveSceneArt(presentation);
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [art.src]);
  if (broken) {
    return (
      <div className="tf-scene-art-fallback" data-testid="scene-art-fallback" aria-hidden>
        <span />
        <span />
        <span />
      </div>
    );
  }
  return <img className="tf-scene-art" src={art.src} style={{ objectPosition: art.focus }} alt="" onError={() => setBroken(true)} />;
}
