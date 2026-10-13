import type { ChatMessage } from "../lib/types";

export default function ChronicleDivider({ message }: { message: ChatMessage }) {
  const context = message.scene_context;
  const scope = message.scope === "party" ? "отряд" : message.scope === "private" ? "личное" : null;
  if (!context && !scope) return null;
  return (
    <div className="tf-chronicle-divider" role="separator" aria-label="Новая сцена">
      <span>{context?.location_name ?? context?.location_id ?? "Новая сцена"}</span>
      {scope && <small>{scope}</small>}
    </div>
  );
}
