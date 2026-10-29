import type { CampaignCard } from "../lib/types";

/** Metadata belongs to the campaign's pinned world, never today's editable draft. */
export default function CampaignWorldLabel({
  campaign,
}: {
  campaign: CampaignCard;
}) {
  return (
    <span className="inline-flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
      <span className="break-words font-medium">
        {campaign.world?.trim() || "Авторский мир"}
      </span>
      {campaign.world_version && (
        <span className="whitespace-nowrap">
          · версия {campaign.world_version}
        </span>
      )}
    </span>
  );
}
