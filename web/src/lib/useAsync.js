import { useState } from "react";
/** Кнопка с запросом: занято, ошибка по-русски от сервера. */
export function useAsync() {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    async function run(fn) {
        setBusy(true);
        setError(null);
        try {
            return await fn();
        }
        catch (e) {
            setError(e instanceof Error ? e.message : String(e));
            return undefined;
        }
        finally {
            setBusy(false);
        }
    }
    return { busy, error, run, setError };
}
