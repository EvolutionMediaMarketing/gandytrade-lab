import { useEffect, useState } from "react";
import { api } from "./api";
import Login from "./Login";
import Workspace from "./Workspace";

type State = { status: "loading" } | { status: "signed-out" } | { status: "signed-in"; username: string };

export default function App() {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    api
      .me()
      .then((u) => setState({ status: "signed-in", username: u.username }))
      .catch(() => setState({ status: "signed-out" }));
  }, []);

  if (state.status === "loading") return <div className="splash">Loading…</div>;
  if (state.status === "signed-out")
    return <Login onSignedIn={(username) => setState({ status: "signed-in", username })} />;
  return (
    <Workspace
      username={state.username}
      onSignedOut={() => setState({ status: "signed-out" })}
    />
  );
}
