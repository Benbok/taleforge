import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import StudioWorkspace from "./StudioWorkspace";

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("StudioWorkspace — 3-этапная Творческая студия", () => {
  it("Шаг 1: отображает форму описания мира, поля замысла и переключатель авторских тайн", () => {
    render(
      <MemoryRouter>
        <StudioWorkspace
          projectId="proj-1"
          initialDraft={{
            title: "Пепельные Архипелаги",
            premise: "Мир летающих островов после катастрофы.",
          }}
        />
      </MemoryRouter>
    );

    expect(screen.getByText(/Шаг 1: Опишите мир и фундаментальные законы/i)).toBeTruthy();
    expect(screen.getByDisplayValue("Пепельные Архипелаги")).toBeTruthy();
    expect(screen.getByDisplayValue("Мир летающих островов после катастрофы.")).toBeTruthy();

    // Секреты мастера скрыты по умолчанию, если не заданы
    expect(screen.queryByLabelText(/Скрытые факты, истинные мотивы NPC/i)).toBeNull();

    // Нажатие кнопки раскрывает приватный блок
    fireEvent.click(screen.getByRole("button", { name: /\+ Добавить авторские секреты/i }));
    expect(screen.getByLabelText(/Скрытые факты, истинные мотивы NPC/i)).toBeTruthy();
  });

  it("Шаг 2: отправка черновика на проверку переключает на диалог с мастером", () => {
    vi.useFakeTimers();

    render(
      <MemoryRouter>
        <StudioWorkspace
          projectId="proj-2"
          initialDraft={{
            title: "Кибер-Неолит",
            premise: "Выживание племен среди нано-руин.",
          }}
        />
      </MemoryRouter>
    );

    const submitBtn = screen.getByRole("button", { name: /ОТПРАВИТЬ МАСТЕРУ НА ПРОВЕРКУ →/i }) as HTMLButtonElement;
    expect(submitBtn.disabled).toBe(false);
    fireEvent.click(submitBtn);

    // Должен отобразиться заголовок шага 2
    expect(screen.getByText(/Шаг 2 · Согласование с мастером/i)).toBeTruthy();
    expect(screen.getByText(/Обсуждение мира и проверка законов/i)).toBeTruthy();

    // Промотка таймера инициализации ревью мастера внутри act()
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(screen.getByText(/Черновик мира «Кибер-Неолит» принят на рассмотрение/i)).toBeTruthy();

    vi.useRealTimers();
  });

  it("Шаг 3: принятие версии отображает неизменяемый слепок и кнопку запуска независимого стола", () => {
    render(
      <MemoryRouter>
        <StudioWorkspace
          projectId="proj-3"
          initialStep="version"
          initialDraft={{
            title: "Глубинный Эфир",
            premise: "Подводные города эпохи стимпанка.",
            laws: "Давление компенсируется эфирными полями.",
          }}
          initialVersion={{
            version: "v1.0",
            published_at: "2026-10-24T18:00:00Z",
            adventure_id: "adv-deep-1",
            draft_revision: 1,
          }}
        />
      </MemoryRouter>
    );

    expect(screen.getByText(/ВЕРСИЯ v1.0/i)).toBeTruthy();
    expect(screen.getByText(/Неизменяемый слепок мира зафиксирован/i)).toBeTruthy();
    expect(screen.getAllByText("Глубинный Эфир").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Подводные города эпохи стимпанка.")).toBeTruthy();
    expect(screen.getByText("Давление компенсируется эфирными полями.")).toBeTruthy();

    // Кнопка запуска нового стола
    const launchLink = screen.getByRole("link", { name: /ЗАПУСТИТЬ СТОЛ \(НОВОЕ ПРОХОЖДЕНИЕ\) →/i });
    expect(launchLink).toBeTruthy();
    expect(launchLink.getAttribute("href")).toBe("/new?pack=adv-deep-1");
  });
});

