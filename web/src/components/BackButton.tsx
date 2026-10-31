import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";

/** Возврат на предыдущую страницу приложения. У первой записи истории (прямая ссылка, новая вкладка) ключ «default»:
 *  назад идти некуда, и ведём в запасной раздел, не выходя из приложения. */
export function useBack(fallback: string) {
  const navigate = useNavigate();
  const { key } = useLocation();
  return useCallback(() => {
    if (key !== "default") navigate(-1);
    else navigate(fallback, { replace: true });
  }, [key, navigate, fallback]);
}

/** Единая кнопка «Назад»: одинаковый вид и место на всех страницах. */
export default function BackButton({ fallback }: { fallback: string }) {
  const back = useBack(fallback);
  return (
    <button
      type="button"
      onClick={back}
      className="btn btn-outline-copper inline-flex min-h-11 items-center gap-1.5 px-3.5 text-sm font-medium"
    >
      <span aria-hidden="true">←</span> Назад
    </button>
  );
}
