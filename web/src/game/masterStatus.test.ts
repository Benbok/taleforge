import { expect, it } from "vitest";
import { STAGES } from "./masterStatus";

it("explains scene preparation separately from narration", () => {
  expect(STAGES.preparing_world).toBe("Мастер подготавливает место…");
});
