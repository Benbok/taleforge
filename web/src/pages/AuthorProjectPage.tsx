import { useParams } from "react-router-dom";
import AuthorWorkspace from "../author/AuthorWorkspace";
import BackButton from "../components/BackButton";
import Header from "../components/Header";

export default function AuthorProjectPage() {
  const { projectId } = useParams();

  return (
    <>
      <Header>
        <BackButton fallback="/author" />
      </Header>
      {projectId ? <AuthorWorkspace projectId={projectId} /> : null}
    </>
  );
}
