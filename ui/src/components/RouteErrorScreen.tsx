import { useEffect } from "react";
import { isRouteErrorResponse, useNavigate, useRouteError } from "react-router-dom";

import { Button } from "./Button";

interface Described {
  title: string;
  message: string;
  detail?: string;
}

function describe(error: unknown): Described {
  if (isRouteErrorResponse(error)) {
    if (error.status === 404) {
      return {
        title: "Page not found",
        message: "The page you were looking for doesn't exist or has moved.",
      };
    }
    return {
      title: `Error ${error.status}`,
      message: error.statusText || "The request could not be completed.",
    };
  }
  const generic = {
    title: "Something went wrong",
    message: "This page hit an unexpected error. Try again, or go back to the start.",
  };
  // Raw error text is for a developer at the console. Production users see the generic
  // message only, so internal details never reach the screen.
  if (import.meta.env.DEV && error instanceof Error) {
    return { ...generic, detail: error.message };
  }
  return generic;
}

/** Full-page screen for an unmatched route or an unhandled render error. Set as the
 *  `errorElement` on routes, so the app never shows React Router's unstyled default. */
export function RouteErrorScreen() {
  const error = useRouteError();
  const navigate = useNavigate();
  const { title, message, detail } = describe(error);

  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="empty-card route-error" role="alert" style={{ margin: "var(--space-8) auto", maxWidth: 480 }}>
      <h1 style={{ margin: 0, fontSize: "1.5rem" }}>{title}</h1>
      <p>{message}</p>
      {detail && <p className="route-error__detail" style={{ fontFamily: "var(--font-mono, monospace)", fontSize: "0.85rem" }}>{detail}</p>}
      <div style={{ display: "flex", gap: "var(--space-2)" }}>
        <Button variant="primary" onClick={() => window.location.reload()}>
          Try again
        </Button>
        <Button variant="secondary" onClick={() => navigate("/")}>
          Go to home
        </Button>
      </div>
    </main>
  );
}
