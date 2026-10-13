/** Thin GraphQL fetch wrapper. No Apollo/urql — this app's query surface is small
 * enough that a normalized cache would be more machinery than value; TanStack Query
 * (in the hooks/ layer) covers caching/refetch/loading state on top of this. */

export class GraphQLRequestError extends Error {
  constructor(
    message: string,
    public readonly graphQLErrors: readonly { message: string }[],
  ) {
    super(message);
    this.name = "GraphQLRequestError";
  }
}

export class UnauthenticatedError extends Error {
  constructor() {
    super("Not authenticated");
    this.name = "UnauthenticatedError";
  }
}

export type Audience = "reseller" | "operator";

export async function graphqlRequest<TData, TVariables extends Record<string, unknown> = Record<string, never>>(
  audience: Audience,
  query: string,
  variables: TVariables,
  idToken: string | null,
): Promise<TData> {
  const base = import.meta.env.VITE_GRAPHQL_URL.replace(/\/$/, "");
  const url = `${base}/${audience}`;
  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(idToken ? { Authorization: `Bearer ${idToken}` } : {}),
      },
      body: JSON.stringify({ query, variables }),
    });
  } catch {
    // fetch() throws a generic TypeError for both "server is down" and "CORS rejected",
    // with no status code to tell them apart. The detailed, URL-bearing message is only
    // useful to someone who can act on it — a developer at the console — never to an end
    // user in production, where it just leaks an internal hostname onto the screen.
    const detail = `Could not reach the API at ${url}. Check that it is running and reachable.`;
    if (import.meta.env.DEV) {
      throw new GraphQLRequestError(detail, []);
    }
    console.error(detail);
    throw new GraphQLRequestError("Could not reach the server right now. Please try again in a moment.", []);
  }

  if (res.status === 401) {
    throw new UnauthenticatedError();
  }

  const body = (await res.json()) as { data?: TData; errors?: { message: string }[] };
  if (body.errors && body.errors.length > 0) {
    throw new GraphQLRequestError(body.errors[0].message, body.errors);
  }
  if (body.data === undefined) {
    throw new GraphQLRequestError("GraphQL response had no data", []);
  }
  return body.data;
}
