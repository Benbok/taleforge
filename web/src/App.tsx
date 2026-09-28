import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./lib/api";
import type { Theme } from "./lib/types";
import Toasts from "./components/Toasts";
import GamePage from "./pages/GamePage";
import Home from "./pages/Home";
import InvitePage from "./pages/InvitePage";
import Welcome from "./pages/Welcome";
import { useSession } from "./stores/session";

const queries = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } } });

export default function App() {
  const { ready, user, boot, setTheme } = useSession();

  useEffect(() => {
    void boot();
    api<Theme>("/api/theme").then(setTheme, () => undefined);
  }, [boot, setTheme]);

  if (!ready) return null;
  return (
    <QueryClientProvider client={queries}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={user ? <Home /> : <Welcome />} />
          <Route path="/invite/:token" element={<InvitePage />} />
          <Route path="/c/:id" element={user ? <GamePage /> : <Navigate to="/" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
      <Toasts />
    </QueryClientProvider>
  );
}
