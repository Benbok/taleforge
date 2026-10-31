import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, expect, it } from "vitest";
import BackButton from "./BackButton";

afterEach(cleanup);

const Where = () => <p data-testid="where">{useLocation().pathname + useLocation().search}</p>;
const app = (start: string) => (
  <MemoryRouter initialEntries={[start]}>
    <Where />
    <Routes>
      <Route path="/" element={<Link to="/c/1">Открыть</Link>} />
      <Route path="/c/:id" element={<BackButton fallback="/?tab=heroes" />} />
    </Routes>
  </MemoryRouter>
);

it("после внутреннего перехода возвращает на предыдущую страницу", () => {
  render(app("/"));
  fireEvent.click(screen.getByText("Открыть"));
  expect(screen.getByTestId("where").textContent).toBe("/c/1");
  fireEvent.click(screen.getByRole("button", { name: /Назад/ }));
  expect(screen.getByTestId("where").textContent).toBe("/");
});

it("при прямом открытии ведёт в запасной раздел и не выходит из приложения", () => {
  render(app("/c/1"));
  fireEvent.click(screen.getByRole("button", { name: /Назад/ }));
  expect(screen.getByTestId("where").textContent).toBe("/?tab=heroes");
});
