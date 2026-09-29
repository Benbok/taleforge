import { describe, expect, it } from "vitest";
import { computePopoverPosition } from "./popoverPosition";

describe("computePopoverPosition", () => {
  it("positions below when space is abundant below anchor", () => {
    const pos = computePopoverPosition(
      { top: 100, bottom: 120, left: 200, right: 300 },
      { cardWidth: 320, padding: 12, windowWidth: 1000, windowHeight: 800 }
    );
    expect(pos.top).toBe(128); // 120 + 8
    expect(pos.bottom).toBeUndefined();
    expect(pos.left).toBe(200);
    expect(pos.top! + pos.maxHeight).toBeLessThanOrEqual(800 - 12);
  });

  it("positions above when anchor is near the bottom of viewport", () => {
    const pos = computePopoverPosition(
      { top: 720, bottom: 740, left: 150, right: 250 },
      { cardWidth: 320, padding: 12, windowWidth: 1000, windowHeight: 800 }
    );
    expect(pos.bottom).toBe(800 - 720 + 8); // 88
    expect(pos.top).toBeUndefined();
    expect(pos.left).toBe(150);
    // top edge in viewport is windowHeight - bottom - maxHeight:
    const topEdge = 800 - pos.bottom! - pos.maxHeight;
    expect(topEdge).toBeGreaterThanOrEqual(12);
  });

  it("clamps left edge when anchor is at the extreme right", () => {
    const pos = computePopoverPosition(
      { top: 100, bottom: 120, left: 950, right: 980 },
      { cardWidth: 320, padding: 12, windowWidth: 1000, windowHeight: 800 }
    );
    // maxLeft = 1000 - 320 - 12 = 668
    expect(pos.left).toBe(668);
  });

  it("clamps left edge when anchor is at the extreme left", () => {
    const pos = computePopoverPosition(
      { top: 100, bottom: 120, left: 0, right: 10 },
      { cardWidth: 320, padding: 12, windowWidth: 1000, windowHeight: 800 }
    );
    expect(pos.left).toBe(12);
  });
});
