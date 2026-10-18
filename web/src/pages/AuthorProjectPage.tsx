import { Link, useParams } from "react-router-dom";
import AuthorWorkspace from "../author/AuthorWorkspace";
import Header from "../components/Header";

export default function AuthorProjectPage() {
  const { projectId } = useParams();
  return (
    <>
      <Header>
        <Link className="text-sm text-muted no-underline hover:text-ink" to="/author">← Проекты</Link>
      </Header>
      {projectId ? <AuthorWorkspace projectId={projectId} /> : null}
    </>
  );
}
