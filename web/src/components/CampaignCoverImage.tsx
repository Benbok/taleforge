import { useState } from "react";
import { useAuthedImage } from "../lib/authedImage";
import ArtworkViewer from "./ArtworkViewer";

/** Обложка мира по защищённой ссылке; пока файл грузится или недоступен, остаётся нейтральная заливка. */
export default function CampaignCoverImage({
  url,
  name,
  className = "",
  expandable = false,
}: {
  url: string;
  name: string;
  className?: string;
  /** Клик открывает обложку на весь экран, как иллюстрации локаций в игре. */
  expandable?: boolean;
}) {
  const src = useAuthedImage(url);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const alt = `Обложка мира «${name}»`;
  const image = src && !failed && (
    <img src={src} alt={alt} className="h-full w-full object-cover" onError={() => setFailed(true)} />
  );
  if (!expandable || !src || failed) {
    return <div className={`overflow-hidden bg-surface-2 ${className}`}>{image}</div>;
  }
  return (
    <>
      <button
        type="button"
        aria-label={`Открыть обложку мира «${name}» на весь экран`}
        title="Рассмотреть обложку"
        onClick={() => setOpen(true)}
        className={`group relative block cursor-zoom-in overflow-hidden bg-surface-2 transition-colors hover:border-accent/60 focus-visible:outline-2 focus-visible:outline-accent ${className}`}
      >
        <span className="block h-full w-full transition-transform duration-300 ease-out group-hover:scale-105">{image}</span>
        <span
          className="pointer-events-none absolute bottom-2 right-2 flex items-center gap-1 rounded-md bg-black/80 px-2 py-0.5 font-mono text-[10px] font-medium text-white/90 opacity-0 transition-opacity duration-150 group-hover:opacity-100"
          aria-hidden="true"
        >
          <span>⤢</span>
          <span>Увеличить</span>
        </span>
      </button>
      {open && (
        <ArtworkViewer
          src={src}
          name={name}
          label={`Обложка мира «${name}»`}
          alt={alt}
          backdropTestId="campaign-cover-backdrop"
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
