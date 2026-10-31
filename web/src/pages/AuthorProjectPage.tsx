import { Link, useParams } from "react-router-dom";
import AuthorWorkspace from "../author/AuthorWorkspace";
import Header from "../components/Header";

export default function AuthorProjectPage() {
  const { projectId } = useParams();

  return (
    <>
      <Header>
        <Link className="btn btn-outline-copper h-8 px-2.5 text-xs font-mono" to="/author">
          ← Проекты
        </Link>
      </Header>
      {projectId ? <AuthorWorkspace projectId={projectId} /> : null}
    </>
  );
}
