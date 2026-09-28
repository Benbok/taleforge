/** Спасброски от смерти: три успеха — стабилизация, три провала — смерть. Бросаются открыто, трекер видят все. */
export default function DeathSaves({ saves, label = "При смерти:" }: { saves: [number, number]; label?: string }) {
  const [succ, fail] = saves;
  return (
    <span
      className="flex items-center gap-1 text-xs"
      title={`Спасброски от смерти: успехов ${succ} из 3, провалов ${fail} из 3`}
      aria-label={`Спасброски от смерти: успехов ${succ}, провалов ${fail}`}
    >
      <span className="whitespace-nowrap text-bad">{label}</span>
      {[0, 1, 2].map((i) => (
        <span key={`s${i}`} className={`h-2.5 w-2.5 rounded-full border border-ok ${i < succ ? "bg-ok" : ""}`} />
      ))}
      <span className="mx-0.5 text-muted">/</span>
      {[0, 1, 2].map((i) => (
        <span key={`f${i}`} className={`h-2.5 w-2.5 rounded-full border border-bad ${i < fail ? "bg-bad" : ""}`} />
      ))}
    </span>
  );
}
