import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import CustomSelect from "../components/CustomSelect";
import { api } from "../lib/api";
import { toast } from "../stores/toasts";

export interface MasterTemper {
  value: string;
  options: { id: string; name: string; description: string }[];
}

/** Нрав ИИ-мастера: как он эмоционально отзывается на броски и поступки героев. Сохраняется сразу при выборе. */
export default function MasterTemperPicker({ campaignId }: { campaignId: string }) {
  const qc = useQueryClient();
  const key = ["master-temper", campaignId];
  const temper = useQuery({ queryKey: key, queryFn: () => api<MasterTemper>(`/api/campaigns/${campaignId}/master-temper`) });
  const [saving, setSaving] = useState(false);

  if (temper.error) {
    return <p className="text-xs text-bad">Нрав мастера не загрузился: {temper.error.message}</p>;
  }
  if (!temper.data) return <p className="text-xs text-muted">Загружаю нрав мастера…</p>;

  const cur = temper.data.options.find((o) => o.id === temper.data.value);
  const choose = async (value: string) => {
    if (value === temper.data.value || saving) return;
    setSaving(true);
    try {
      const res = await api<MasterTemper>(`/api/campaigns/${campaignId}/master-temper`, { method: "PUT", body: { value } });
      qc.setQueryData(key, res);
      toast.ok(`Нрав мастера: ${res.options.find((o) => o.id === res.value)?.name ?? res.value}. Со следующего хода`);
    } catch (e) {
      toast.error(`Нрав мастера не сохранён: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <CustomSelect
        value={temper.data.value}
        options={temper.data.options.map((o) => ({ value: o.id, label: o.name, sublabel: o.description }))}
        onChange={choose}
        disabled={saving}
        ariaLabel="Нрав ИИ-мастера"
      />
      {cur && <p className="text-xs text-muted">{saving ? "Сохраняю…" : cur.description}</p>}
    </div>
  );
}
