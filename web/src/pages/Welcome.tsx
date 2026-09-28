import { ThemeToggle } from "../components/Header";
import AuthForm from "../components/AuthForm";

export default function Welcome() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-6 px-4 py-10">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-semibold">Taleforge</h1>
        <ThemeToggle />
      </div>
      <p className="font-narration text-lg text-muted">
        Ролевая игра в тексте: мастер ведёт историю по правилам D&amp;D, а вы решаете, что делают ваши герои.
      </p>
      <AuthForm />
    </main>
  );
}
