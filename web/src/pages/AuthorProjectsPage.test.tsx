import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";
import { mockApi, renderWithClient } from "../author/testkit";
import type { User } from "../lib/types";
import { useSession } from "../stores/session";
import AdminPage from "./AdminPage";
import AuthorProjectsPage from "./AuthorProjectsPage";

beforeEach(() => useSession.setState({ user: { id: "u_author", name: "Автор", platform_role: "admin" } as User }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); useSession.setState({ user: null }); });

function catalogue() {
  return mockApi(({ url }) => {
    if (url === "/api/packs" || url === "/api/author/projects") return { body: [] };
    if (url === "/api/admin/modules") return { body: [{ id: "mod_old", title: "Ранее загруженная книга", status: "review", maps: 0, pages: 3, counts: {}, pack_id: null }] };
    return undefined;
  });
}

it("opens the existing book import and library from the author workspace without starting generation", async () => {
  const mock = catalogue();
  renderWithClient(<AuthorProjectsPage />, undefined, "/author");
  fireEvent.click(screen.getByRole("tab", { name: "Импорт кампаний" }));
  expect(await screen.findByLabelText("Книга приключения")).toBeTruthy();
  expect(await screen.findByText("Ранее загруженная книга")).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Создать новое приключение" })).toBeNull();
  expect(mock.calls.every((c) => c.method === "GET")).toBe(true);
  fireEvent.click(screen.getByRole("tab", { name: "Мои проекты" }));
  expect(await screen.findByRole("heading", { name: "Создать новое приключение" })).toBeTruthy();
  expect(screen.queryByLabelText("Книга приключения")).toBeNull();
});

it("redirects the old admin bookmark to the author import tab", async () => {
  const mock = catalogue();
  renderWithClient(<Routes>
    <Route path="/admin" element={<AdminPage />} />
    <Route path="/author" element={<AuthorProjectsPage />} />
  </Routes>, undefined, "/admin?tab=modules");
  expect(await screen.findByRole("heading", { name: "Пространство автора" })).toBeTruthy();
  await waitFor(() => expect(screen.getByRole("tab", { name: "Импорт кампаний" }).getAttribute("aria-selected")).toBe("true"));
  expect(await screen.findByLabelText("Книга приключения")).toBeTruthy();
  expect(mock.calls.every((c) => c.method === "GET")).toBe(true);
});
