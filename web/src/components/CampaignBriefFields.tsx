import { useQuery } from "@tanstack/react-query";
import BriefForm from "../cabinet/BriefForm";
import { api } from "../lib/api";
import type { BriefIn } from "../lib/api.gen";
import type { Brief, CampaignOptions } from "../lib/campaign";

interface Props {
  value: BriefIn;
  onChange(next: BriefIn): void;
}

/** Общая анкета: та же BriefForm и те же варианты с сервера, что на /new, но с контролируемым черновиком. */
export default function CampaignBriefFields({ value, onChange }: Props) {
  // тот же ключ, что у страницы новой кампании: варианты анкеты загружаются один раз на оба пути
  const opts = useQuery({ queryKey: ["campaign-options"], queryFn: () => api<CampaignOptions>("/api/campaign-options") });
  if (!opts.data) return <p className="text-sm text-muted">Загрузка анкеты…</p>;
  return <BriefForm brief={value as Brief} opts={opts.data.brief} onChange={(b) => onChange(b as BriefIn)} />;
}
