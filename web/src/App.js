import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./lib/api";
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
        api("/api/theme").then(setTheme, () => undefined);
    }, [boot, setTheme]);
    if (!ready)
        return null;
    return (_jsxs(QueryClientProvider, { client: queries, children: [_jsx(BrowserRouter, { children: _jsxs(Routes, { children: [_jsx(Route, { path: "/", element: user ? _jsx(Home, {}) : _jsx(Welcome, {}) }), _jsx(Route, { path: "/invite/:token", element: _jsx(InvitePage, {}) }), _jsx(Route, { path: "/c/:id", element: user ? _jsx(GamePage, {}) : _jsx(Navigate, { to: "/", replace: true }) }), _jsx(Route, { path: "*", element: _jsx(Navigate, { to: "/", replace: true }) })] }) }), _jsx(Toasts, {})] }));
}
