import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../lib/types";
import { chronicleEntries } from "./chronicle";

const msg = (id: string, kind: string, location_id?: string, scope: ChatMessage["scope"] = "public"): ChatMessage => ({
  id,
  seq: Number(id),
  kind,
  seat_id: null,
  author: null,
  content: id,
  whisper: scope === "private",
  scope,
  scene_context: location_id ? { location_id, location_name: location_id } : null,
  data: null,
  created_at: null,
});

describe("границы хроники", () => {
  it("does not let OOC and dice rolls split an episode", () => {
    const entries = chronicleEntries([
      msg("1", "narration", "hall"),
      msg("2", "ooc"),
      msg("3", "roll"),
      msg("4", "speech", "hall", "party"),
      msg("5", "narration", "crypt"),
    ]);
    expect(entries.map((entry) => [entry.message.id, entry.divider])).toEqual([
      ["1", false],
      ["2", false],
      ["3", false],
      ["4", true],
      ["5", true],
    ]);
  });

  it("keeps private whispers out of public chronicle boundaries", () => {
    const entries = chronicleEntries([msg("1", "narration", "hall"), msg("2", "whisper", "crypt", "private"), msg("3", "narration", "hall")]);
    expect(entries.map((entry) => [entry.message.id, entry.divider])).toEqual([["1", false], ["2", false], ["3", false]]);
  });

  it("supports story-only and OOC filters", () => {
    expect(chronicleEntries([msg("1", "ooc"), msg("2", "speech", "hall")], { onlyStory: true }).map((x) => x.message.id)).toEqual([]);
    expect(chronicleEntries([msg("1", "ooc"), msg("2", "speech", "hall")], { hideOoc: true }).map((x) => x.message.id)).toEqual(["2"]);
  });
});
