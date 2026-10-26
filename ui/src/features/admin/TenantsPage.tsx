import { useState, type FormEvent } from "react";
import { Search } from "lucide-react";

import { DataTable, type Column } from "../../components/DataTable";
import { Drawer } from "../../components/Drawer";
import { FilterMenu } from "../../components/FilterMenu";
import { InfoTag } from "../../components/InfoTag";
import { PageHeader } from "../../components/PageHeader";
import { StatusBadge } from "../../components/StatusBadge";
import {
  useBindings,
  useConnections,
  useCreateBinding,
  usePauseWebhookEndpoint,
  useRegisterResellerWebhook,
  useRemoveBinding,
  useResellers,
  useResumeWebhookEndpoint,
  useVerifyBinding,
  useWebhookEndpoints,
} from "../../hooks/useAdmin";
import type { Binding, WebhookEndpoint } from "../../api/queries/admin";
import { statusLabel } from "../../lib/statusLabel";

const STATUS_FILTERS = ["all", "TO_VERIFY", "VERIFIED", "REMOVED"] as const;
const STATUS_OPTIONS = STATUS_FILTERS.map((s) => ({ value: s, label: s === "all" ? "All" : statusLabel(s) }));
const EMPTY_RESELLER = { tenantId: "", connectionId: "", erpCustomerId: "", name: "" };
// How we authenticate to a reseller's webhook URL. The secret is sent as the header value
// (API key), the bearer token, or the password (basic). NONE sends no credential at all.
const WEBHOOK_AUTH_OPTIONS = [
  { value: "NONE", label: "None (signature only)" },
  { value: "API_KEY_HEADER", label: "API key in a header" },
  { value: "BEARER_TOKEN", label: "Bearer token" },
  { value: "BASIC", label: "Basic (username + password)" },
] as const;
type WebhookAuthType = (typeof WEBHOOK_AUTH_OPTIONS)[number]["value"];
const EMPTY_WEBHOOK = { name: "", url: "", authType: "NONE" as WebhookAuthType, headerName: "X-API-Key", username: "", secret: "" };

// What the drawer is showing. `secret` is shown once, straight after a webhook is added.
type Panel =
  | { kind: "register" }
  | { kind: "webhooks"; tenantId: string; resellerName: string }
  | { kind: "webhook"; tenantId: string; resellerName: string }
  | { kind: "secret"; resellerName: string; url: string; signingSecret: string }
  | null;

export function TenantsPage() {
  const { data: bindings, isLoading, error } = useBindings();
  const { data: connections } = useConnections();
  const { data: resellers } = useResellers();
  const createBinding = useCreateBinding();
  const registerWebhook = useRegisterResellerWebhook();
  const pauseWebhook = usePauseWebhookEndpoint();
  const resumeWebhook = useResumeWebhookEndpoint();
  const verifyBinding = useVerifyBinding();
  const removeBinding = useRemoveBinding();
  const [form, setForm] = useState(EMPTY_RESELLER);
  const [webhookForm, setWebhookForm] = useState(EMPTY_WEBHOOK);
  const [drawer, setDrawer] = useState<Panel>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<(typeof STATUS_FILTERS)[number]>("all");

  const resellerNameById = new Map((resellers ?? []).map((r) => [r.tenantId, r.name]));
  const webhookUrlsById = new Map((resellers ?? []).map((r) => [r.tenantId, r.webhookUrls.join(", ")]));

  const rows = (bindings ?? [])
    .filter((b) => status === "all" || b.status === status)
    .filter((b) =>
      [b.tenantId, resellerNameById.get(b.tenantId) ?? "", b.connectionId, b.erpCustomerId].join(" ").toLowerCase().includes(search.toLowerCase()),
    );

  const columns: Column<Binding>[] = [
    {
      key: "tenant",
      header: "Reseller",
      render: (b) => resellerNameById.get(b.tenantId) ?? b.tenantId,
      sortValue: (b) => resellerNameById.get(b.tenantId) ?? b.tenantId,
    },
    { key: "tenantId", header: "Reseller ID", render: (b) => <span className="id">{b.tenantId}</span>, sortValue: (b) => b.tenantId },
    { key: "connection", header: "Connection", render: (b) => b.connectionId, sortValue: (b) => b.connectionId },
    {
      key: "webhook",
      header: "Webhook URL",
      render: (b) => <span className="mono">{webhookUrlsById.get(b.tenantId) || "—"}</span>,
      sortValue: (b) => webhookUrlsById.get(b.tenantId) ?? "",
    },
    { key: "customer", header: "ERP customer ID", render: (b) => <span className="mono">{b.erpCustomerId}</span>, sortValue: (b) => b.erpCustomerId },
    { key: "status", header: "Status", render: (b) => <StatusBadge status={statusLabel(b.status)} />, sortValue: (b) => b.status },
    {
      key: "actions",
      header: "",
      render: (b) =>
        b.status === "REMOVED" ? null : (
          <span className="actions">
            {b.status !== "VERIFIED" && (
              <button className="erp-btn erp-btn--secondary erp-btn--sm" type="button" onClick={() => verifyBinding.mutate({ bindingId: b.bindingId })}>
                Verify
              </button>
            )}
            <button
              className="erp-btn erp-btn--ghost erp-btn--sm"
              type="button"
              onClick={() =>
                setDrawer({ kind: "webhooks", tenantId: b.tenantId, resellerName: resellerNameById.get(b.tenantId) ?? b.tenantId })
              }
            >
              Webhooks
            </button>
            <button className="erp-btn erp-btn--ghost erp-btn--sm" type="button" onClick={() => removeBinding.mutate({ bindingId: b.bindingId })}>
              Remove
            </button>
          </span>
        ),
    },
  ];

  async function handleRegister(e: FormEvent) {
    e.preventDefault();
    await createBinding.mutateAsync(form);
    setForm(EMPTY_RESELLER);
    setDrawer(null);
  }

  async function handleWebhook(e: FormEvent) {
    e.preventDefault();
    if (drawer?.kind !== "webhook") return;
    const authParams: Record<string, string> =
      webhookForm.authType === "API_KEY_HEADER" ? { header_name: webhookForm.headerName.trim() || "X-API-Key" }
      : webhookForm.authType === "BASIC" ? { username: webhookForm.username.trim() }
      : {};
    const { endpoint, signingSecret } = await registerWebhook.mutateAsync({
      tenantId: drawer.tenantId,
      name: webhookForm.name,
      url: webhookForm.url,
      authType: webhookForm.authType,
      authParams,
      authSecret: webhookForm.authType === "NONE" ? null : webhookForm.secret,
    });
    setWebhookForm(EMPTY_WEBHOOK);
    setDrawer({ kind: "secret", resellerName: drawer.resellerName, url: endpoint.url, signingSecret });
  }

  // The reseller whose webhooks the drawer is showing, if any (every mode but register/secret).
  const drawerTenantId = drawer && drawer.kind !== "register" && drawer.kind !== "secret" ? drawer.tenantId : "";
  const { data: endpoints, isLoading: endpointsLoading } = useWebhookEndpoints(drawer?.kind === "webhooks" ? drawerTenantId : null);

  function closeDrawer() {
    setDrawer(null);
    setForm(EMPTY_RESELLER);
    setWebhookForm(EMPTY_WEBHOOK);
  }

  const drawerTitle =
    drawer?.kind === "register"
      ? "Register reseller"
      : drawer?.kind === "webhooks"
        ? `Webhooks for ${drawer.resellerName}`
        : drawer?.kind === "webhook"
          ? `Add webhook for ${drawer.resellerName}`
          : drawer?.kind === "secret"
            ? `Webhook added for ${drawer.resellerName}`
            : "";

  const endpointColumns: Column<WebhookEndpoint>[] = [
    { key: "name", header: "Name", render: (e) => e.name, sortValue: (e) => e.name },
    { key: "url", header: "Web address", render: (e) => <span className="mono">{e.url}</span>, sortValue: (e) => e.url },
    { key: "auth", header: "Authentication", render: (e) => e.authType, sortValue: (e) => e.authType },
    {
      key: "status",
      header: "Status",
      render: (e) => <StatusBadge status={e.isActive ? "Active" : "Paused"} />,
      sortValue: (e) => (e.isActive ? "Active" : "Paused"),
    },
    {
      key: "actions",
      header: "",
      render: (e) =>
        e.isActive ? (
          <button
            className="erp-btn erp-btn--ghost erp-btn--sm"
            type="button"
            onClick={() => pauseWebhook.mutate({ tenantId: drawerTenantId, endpointId: e.endpointId })}
          >
            Pause
          </button>
        ) : (
          <button
            className="erp-btn erp-btn--ghost erp-btn--sm"
            type="button"
            onClick={() => resumeWebhook.mutate({ tenantId: drawerTenantId, endpointId: e.endpointId })}
          >
            Resume
          </button>
        ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Resellers"
        subtitle="Each reseller has a customer link into every ERP connection it buys from."
      />

      <div className="toolbar">
        <div className="search-input">
          <Search size={15} strokeWidth={2} className="search-input__icon" />
          <input
            className="input"
            type="search"
            placeholder="Search by reseller, connection, or ERP customer id"
            style={{ width: 300 }}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <FilterMenu groups={[{ label: "Status", options: STATUS_OPTIONS, value: status, onChange: (v) => setStatus(v as (typeof STATUS_FILTERS)[number]) }]} />
        <button
          className="erp-btn erp-btn--primary"
          type="button"
          style={{ marginLeft: "auto" }}
          onClick={() => setDrawer({ kind: "register" })}
        >
          Register reseller
        </button>
      </div>
      {error && <div className="callout callout--danger">Could not load resellers: {error.message}</div>}
      <DataTable columns={columns} rows={rows} rowKey={(b) => b.bindingId} isLoading={isLoading} emptyMessage="No resellers match this filter" pageSize={10} />

      <Drawer open={drawer !== null} onClose={closeDrawer} title={drawerTitle}>
        {drawer?.kind === "register" && (
          <form className="stack" onSubmit={handleRegister}>
            <div className="grid2">
              <div className="field">
                <label htmlFor="name">Reseller name</label>
                <input className="input" id="name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              </div>
              <div className="field">
                <label htmlFor="tenantId">
                  Reseller ID <InfoTag text="The stable internal id for this reseller — never shown as the primary label, only the name is." />
                </label>
                <input className="input" id="tenantId" value={form.tenantId} onChange={(e) => setForm({ ...form, tenantId: e.target.value })} required />
              </div>
              <div className="field">
                <label htmlFor="connectionId">Connection</label>
                <select className="input" id="connectionId" value={form.connectionId} onChange={(e) => setForm({ ...form, connectionId: e.target.value })} required>
                  <option value="">Select a connection</option>
                  {(connections ?? []).map((c) => (
                    <option key={c.connectionId} value={c.connectionId}>
                      {c.instanceLabel} ({c.connectionId})
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="erpCustomerId">
                  ERP customer ID <InfoTag text="The reseller's customer record ID inside this ERP connection — operator-only, never shown to the reseller." />
                </label>
                <input
                  className="input"
                  id="erpCustomerId"
                  value={form.erpCustomerId}
                  onChange={(e) => setForm({ ...form, erpCustomerId: e.target.value })}
                  required
                />
              </div>
            </div>
            {createBinding.error && <div className="callout callout--danger">{(createBinding.error as Error).message}</div>}
            <div className="actions">
              <button className="erp-btn erp-btn--primary" type="submit" disabled={createBinding.isPending}>
                {createBinding.isPending ? "Saving…" : "Create link"}
              </button>
            </div>
          </form>
        )}

        {drawer?.kind === "webhooks" && (
          <div className="stack">
            <div className="actions">
              <button
                className="erp-btn erp-btn--primary"
                type="button"
                onClick={() => setDrawer({ kind: "webhook", tenantId: drawer.tenantId, resellerName: drawer.resellerName })}
              >
                Add webhook
              </button>
            </div>
            <DataTable
              columns={endpointColumns}
              rows={endpoints ?? []}
              rowKey={(e) => e.endpointId}
              isLoading={endpointsLoading}
              emptyMessage="No webhook addresses yet for this reseller."
              pageSize={10}
            />
          </div>
        )}

        {drawer?.kind === "webhook" && (
          <form className="stack" onSubmit={handleWebhook}>
            <div className="field">
              <label htmlFor="webhookName">
                Name <InfoTag text="What this endpoint is for, such as Order updates." />
              </label>
              <input className="input" id="webhookName" value={webhookForm.name} onChange={(e) => setWebhookForm({ ...webhookForm, name: e.target.value })} required />
            </div>
            <div className="field">
              <label htmlFor="webhookUrl">Web address</label>
              <input
                className="input"
                id="webhookUrl"
                type="url"
                placeholder="https://reseller.example.com/hooks/orders"
                value={webhookForm.url}
                onChange={(e) => setWebhookForm({ ...webhookForm, url: e.target.value })}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="webhookAuth">
                Authentication <InfoTag text="How we prove ourselves to this address. Every request is also signed, so this is in addition to the signature." />
              </label>
              <select
                className="input"
                id="webhookAuth"
                value={webhookForm.authType}
                onChange={(e) => setWebhookForm({ ...webhookForm, authType: e.target.value as WebhookAuthType, secret: "" })}
              >
                {WEBHOOK_AUTH_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            {webhookForm.authType === "API_KEY_HEADER" && (
              <div className="field">
                <label htmlFor="webhookHeader">Header name</label>
                <input className="input" id="webhookHeader" placeholder="X-API-Key" value={webhookForm.headerName} onChange={(e) => setWebhookForm({ ...webhookForm, headerName: e.target.value })} />
              </div>
            )}
            {webhookForm.authType === "BASIC" && (
              <div className="field">
                <label htmlFor="webhookUsername">Username</label>
                <input className="input" id="webhookUsername" value={webhookForm.username} onChange={(e) => setWebhookForm({ ...webhookForm, username: e.target.value })} required />
              </div>
            )}
            {webhookForm.authType !== "NONE" && (
              <div className="field">
                <label htmlFor="webhookSecret">
                  {webhookForm.authType === "API_KEY_HEADER" ? "API key" : webhookForm.authType === "BASIC" ? "Password" : "Token"}
                </label>
                <input className="input" id="webhookSecret" type="password" value={webhookForm.secret} onChange={(e) => setWebhookForm({ ...webhookForm, secret: e.target.value })} required />
              </div>
            )}
            {registerWebhook.error && <div className="callout callout--danger">{(registerWebhook.error as Error).message}</div>}
            <div className="actions">
              <button className="erp-btn erp-btn--primary" type="submit" disabled={registerWebhook.isPending}>
                {registerWebhook.isPending ? "Saving…" : "Add webhook"}
              </button>
            </div>
          </form>
        )}

        {drawer?.kind === "secret" && (
          <div className="stack">
            <p>
              Send this signing secret to <b>{drawer.resellerName}</b> for <span className="mono">{drawer.url}</span>.
              It is shown only once. Each request is signed with it so the reseller can check it came from us.
            </p>
            <pre className="mono" style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{drawer.signingSecret}</pre>
            <div className="actions">
              <button className="erp-btn erp-btn--ghost" type="button" onClick={() => void navigator.clipboard?.writeText(drawer.signingSecret)}>
                Copy secret
              </button>
              <button className="erp-btn erp-btn--primary" type="button" onClick={closeDrawer}>
                Done
              </button>
            </div>
          </div>
        )}
      </Drawer>
    </>
  );
}
