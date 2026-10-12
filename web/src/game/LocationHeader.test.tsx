import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useInspector } from "./inspector";
import LocationHeader from "./LocationHeader";
import type { Scene } from "../lib/types";

const scene = (overrides: Partial<Scene> = {}): Scene => ({
  mode: "free",
  round: 0,
  location: { id: "loc_bay", name: "Старая бухта" },
  presentation: { preset: "coast", period: "dusk", weather: "fog", illustration_key: null },
  entities: [],
  turn: null,
  ...overrides,
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  useInspector.setState({ id: null, label: "", anchor: null });
});

beforeEach(() => localStorage.clear());

describe("шапка локации", () => {
  it("shows known place facts and opens the existing entity inspector", () => {
    render(<LocationHeader scene={scene()} />);
    expect(screen.getByRole("button", { name: "Старая бухта" })).toBeTruthy();
    expect(screen.getByText("Сумерки · Туман")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Старая бухта" }));
    expect(useInspector.getState().id).toBe("loc_bay");
  });

  it("has an accessible neutral fallback for an unknown place", () => {
    render(<LocationHeader scene={null} />);
    expect(screen.getByText("Место ещё не названо")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Место ещё не названо" })).toBeNull();
  });

  it("collapses and restores the art while keeping the place name", () => {
    render(<LocationHeader scene={scene()} />);
    const toggle = screen.getByRole("button", { name: /Свернуть шапку/ });
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByRole("button", { name: "Старая бухта" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Развернуть шапку/ }));
    expect(screen.getByRole("button", { name: /Свернуть шапку/ }).getAttribute("aria-expanded")).toBe("true");
  });

  it("uses the inline fallback when an artwork image fails", () => {
    render(<LocationHeader scene={scene({ presentation: { preset: "coast", period: null, weather: null, illustration_key: "missing" } })} />);
    const image = document.querySelector("img.tf-scene-art") as HTMLImageElement;
    expect(image).toBeTruthy();
    fireEvent.error(image);
    expect(screen.getByTestId("scene-art-fallback")).toBeTruthy();
  });
});
