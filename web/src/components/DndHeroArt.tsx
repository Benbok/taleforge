import { useSession } from "../stores/session";

/**
 * Архитектурно-анатомическая гравюра для мира D&D:
 * Анатомический разрез дракона (Draco Celestialis), парящий двадцатигранник D20
 * в астролябии, срез подземелья/сокровищницы и силуэты искателей приключений.
 * Выполнена в стилистике архивных чертежей Taleforge.
 */
export default function DndHeroArt({
  className,
  mode: propMode,
}: {
  className?: string;
  mode?: "dark" | "light";
}) {
  const sessionMode = useSession((s) => s.mode);
  const isLight = (propMode ?? sessionMode) === "light";

  return (
    <div
      aria-hidden="true"
      className={
        className ??
        "pointer-events-none absolute inset-0 h-full w-full select-none overflow-hidden"
      }
    >
      <img
        src={isLight ? "/dnd-hero-banner.webp" : "/dnd-hero-banner-dark.webp"}
        alt=""
        loading="eager"
        decoding="async"
        className="h-full w-full object-cover object-[80%_center] opacity-85 transition-opacity duration-300"
      />
    </div>
  );
}
