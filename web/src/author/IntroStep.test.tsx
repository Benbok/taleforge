import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import IntroStep from "./IntroStep";
import { mockApi, renderWithClient } from "./testkit";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const intro = (over: object = {}) => ({
  text: "Туман над бухтой.",
  voices: [],
  provider: null,
  voice: null,
  parts: 1,
  current: true,
  providers: { voicestudio: true, gemini: false },
  ...over,
});

function mount(handler: Parameters<typeof mockApi>[0]) {
  const mock = mockApi(handler);
  const onQueued = vi.fn();
  renderWithClient(<IntroStep projectId="ap_1" revision={7} running={false} status="not_requested" errorCode={null} onQueued={onQueued} />);
  return { mock, onQueued };
}

it("выбор источника: облако недоступно, по умолчанию бесплатный локальный голос", async () => {
  const { mock } = mount((c) =>
    c.url.endsWith("/intro") && c.method === "GET"
      ? { body: intro() }
      : c.url.endsWith("/vs-profiles")
        ? { body: [{ id: "p1", name: "Рассказчик" }] }
        : c.url.endsWith("/intro") && c.method === "POST"
          ? { status: 202, body: { job_id: "aj_i", stage: "intro", status: "queued", source_revision: 7 } }
          : undefined,
  );
  const textbox = (await screen.findByRole("textbox", { name: "Текст вступления" })) as HTMLTextAreaElement;
  const cloud = screen.getByRole("radio", { name: /Облако — Gemini/ }) as HTMLInputElement;
  expect(cloud.disabled).toBe(true);
  expect((screen.getByRole("radio", { name: /Локально — Voice Studio/ }) as HTMLInputElement).checked).toBe(true);
  expect(textbox.value).toBe("Туман над бухтой.");
  fireEvent.change(await screen.findByRole("combobox"), { target: { value: "p1" } });
  fireEvent.click(screen.getByRole("button", { name: "Переозвучить" }));
  await waitFor(() => expect(mock.calls.some((c) => c.method === "POST" && c.url.endsWith("/intro"))).toBe(true));
  expect(mock.calls.find((c) => c.method === "POST" && c.url.endsWith("/intro"))?.body).toMatchObject({
    provider: "voicestudio",
    voice: "p1",
    rewrite: false,
    voiced: true,
    expected_revision: 7,
  });
});

it("свой текст сохраняется, а устаревшее вступление помечено", async () => {
  const { mock } = mount((c) =>
    c.url.endsWith("/intro") && c.method === "GET"
      ? { body: intro({ current: false }) }
      : c.url.endsWith("/intro/text")
        ? { body: intro({ text: "Своё начало." }) }
        : c.url.endsWith("/vs-profiles")
          ? { body: [] }
          : undefined,
  );
  expect(await screen.findByText(/для прежней версии сюжета/)).toBeTruthy();
  fireEvent.change(screen.getByRole("textbox", { name: "Текст вступления" }), { target: { value: "Своё начало." } });
  fireEvent.click(screen.getByRole("button", { name: "Сохранить свой текст" }));
  await waitFor(() => expect(mock.calls.some((c) => c.url.endsWith("/intro/text"))).toBe(true));
  expect(mock.calls.find((c) => c.url.endsWith("/intro/text"))).toMatchObject({ method: "PUT", body: { text: "Своё начало.", expected_revision: 7 } });
});


it("«Переписать только текст» просит новый текст без записи", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const { mock } = mount((c) =>
    c.url.endsWith("/intro") && c.method === "GET"
      ? { body: intro({ voices: [{ id: "v1", duration: 2 }], provider: "voicestudio" }) }
      : c.url.endsWith("/vs-profiles")
        ? { body: [] }
        : c.url.endsWith("/intro") && c.method === "POST"
          ? { status: 202, body: { job_id: "aj_t", stage: "intro", status: "queued", source_revision: 7 } }
          : undefined,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Переписать только текст" }));
  await waitFor(() => expect(mock.calls.some((c) => c.method === "POST" && c.url.endsWith("/intro"))).toBe(true));
  expect(mock.calls.find((c) => c.method === "POST" && c.url.endsWith("/intro"))?.body).toMatchObject({ rewrite: true, voiced: false });
});
