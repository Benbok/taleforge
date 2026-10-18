import type { BriefIn } from "../lib/api.gen";

const LENGTHS: [NonNullable<BriefIn["length"]>, string][] = [
  ["oneshot", "Один вечер"],
  ["short", "Короткая"],
  ["long", "Длинная"],
];
const THREATS: [NonNullable<BriefIn["threat"]>, string][] = [
  ["personal", "Личная"],
  ["regional", "Региональная"],
  ["world", "Мировая"],
];

interface Props {
  value: BriefIn;
  onChange(next: BriefIn): void;
}

/** Общая анкета: контролируемый черновик без собственного состояния, чтобы её читали и /new, и пространство автора. */
export default function CampaignBriefFields({ value, onChange }: Props) {
  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="font-heading text-sm text-muted">Анкета</legend>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">Длина</span>
        <select className="min-h-11 rounded-lg border border-line bg-raised px-2" value={value.length ?? ""} onChange={(e) => onChange({ ...value, length: (e.target.value || null) as BriefIn["length"] })}>
          <option value="">Не задано</option>
          {LENGTHS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">Угроза</span>
        <select className="min-h-11 rounded-lg border border-line bg-raised px-2" value={value.threat ?? ""} onChange={(e) => onChange({ ...value, threat: (e.target.value || null) as BriefIn["threat"] })}>
          <option value="">Не задано</option>
          {THREATS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted">Пожелания</span>
        <textarea className="min-h-24 rounded-lg border border-line bg-raised p-2" value={value.wishes ?? ""} onChange={(e) => onChange({ ...value, wishes: e.target.value })} />
      </label>
    </fieldset>
  );
}
