# Proposal — ERP connections and ERP mapping, redesigned

> **Status update (2026-10-15): superseded by what was actually built.** Keep reading for
> the component-level rules (badge roles, button variants, 32px density, tiles-as-filters,
> inspector pattern) — those still apply. But two things this proposal assumed turned out
> different once built:
>
> 1. **"ERP mapping" is two different features, not one.** This proposal's "Mappings
>    workspace" (`mappings-workspace.mock.html`) means reseller customer-links + item
>    ownership — exactly what its own Open Question 1 flagged as ambiguous ("is there a
>    third mapping... field-level mapping?"). The feature actually built and shipped is
>    that third one: a schema/field mapping from a brand-new ERP's exposed fields onto the
>    platform's canonical order fields, LLM-proposed, human-reviewed, then handed to a
>    code-generation service that writes the adapter and opens a PR. Customer links still
>    exist (`TenantsPage`), but as a plain table on the resellers page, not this workspace.
>    Current source of truth: `aidlc-docs/construction/U4-admin/functional-design/frontend-components.md`.
> 2. **Connections can now exist before an adapter does** (ADR-0021) — this proposal's
>    `connections.mock.html` assumed every connection is one of a few known, pre-coded ERP
>    types (the "ERP system" `<select>` in the Add form). The real `/admin/connections`
>    page has to additionally support registering a connection for an ERP with *no* adapter
>    yet (open `erp_type`, a generic declarative auth picker, a derived "Adapter
>    ready"/"Needs mapping" state) — a case this mock's health-tiles-and-table pattern
>    didn't anticipate and wasn't adapted to prove out.
>
> Said differently: adapt this proposal's *patterns* (tiles-as-filters, toolbar, inspector,
> table density) the next time either screen is touched again — don't rebuild against its
> exact field list or form shape, which no longer matches the product.

**Status:** proposed, for review. Not approved, and no existing screen has been changed.
**Scope:** UI only. Backend, data model and APIs are unchanged.
**Built on:** the existing design system — same tokens, `erp-btn` / `erp-badge` / `erp-table`
components, same lifecycle words, badge roles and accessibility rules in
`design/design-system/README.md`. No new colours or fonts.

Mocks (open in a browser, toggle light/dark top right):

- `connections.mock.html` — ERP connections list + add/edit form
- `mappings-workspace.mock.html` — the unified Mappings workspace (customers + items)

---

## What's being redesigned, and why

Two operator surfaces today don't scale past a handful of records and spread the same
job across different layouts:

1. **ERP connections** (`screens/AdminConnections.dc.html`) — a split table with a single
   fixed detail panel. Fine for 5 connections; at 25+ there's no search, no filter, no
   health summary, no pagination, and **Add / Edit are not designed at all**.
2. **ERP mapping** — the act of linking a portal record to the ERP record that owns it.
   Today it's two unrelated screens: **customer links** (inside
   `AdminTenantDetail.dc.html`, one reseller at a time) and **item ownership**
   (`AdminItemOwnership.dc.html`, one conflict at a time). The README itself lists "the
   mapping viewer or editor" as **not designed**. Both resolve records one by one, which
   is the opposite of "scales for multiple records".

The goal you set: **easy to understand** and **scales to many records**. The way to get
both is one consistent, learnable pattern applied everywhere, plus bulk operations on top.

---

## The core idea: one pattern, learned once

Every list in the admin uses the same five-part frame. Learn it on connections, and
mappings, resellers and failed messages all work the same way.

```
Status tiles  →  see the scale, click a tile to filter
Toolbar       →  search + scoping filters + sort
Bulk bar      →  appears when rows are selected; acts on many at once
Data table    →  32px rows, identifier first, status badge, confidence
Inspector     →  right-hand panel for the single-record deep dive
```

This is the same `erp-table` + `panel` you already have. What's new is the **status
tiles that double as filters**, the **toolbar**, the **bulk action bar**, and promoting
the fixed detail panel into a reusable **inspector**. All are added as `.x-` classes in
the mocks so nothing in `bundle.css` changes yet.

---

## 1. ERP connections

**Health first.** Four tiles across the top (All / Healthy / Slow / Unreachable) give the
one answer an operator opens this page for — "is anything broken?" — before any scrolling.
Each tile is also a filter.

**A list that scales.** Search by name or base URL; filter by ERP type and environment;
sort by health, queue depth or name; paginate. A compact "last 2 h" sparkline per row
shows a trend without opening anything. Row actions (Test) are inline.

**Add / Edit, finally designed.** A single grouped form — ERP, endpoint, authentication,
behaviour, capabilities — with **Test connection** required before **Save**. Secrets show
as masked and carry "stored encrypted, never shown after saving", matching the existing
copy.

**Detail** moves to its own route (`/admin/connections/:id`) with tabs: Overview, Errors,
Mappings (customers + items this connection owns), Activity. That keeps the list page light
and gives connection-scoped mappings a home.

See `connections.mock.html`.

---

## 2. The Mappings workspace

One screen, route `/admin/mappings`, with a **segmented control** to switch what you're
mapping: **Customers** or **Items**. Both share the exact same frame, so there is one
mental model instead of two screens.

**Built for many records at once:**

- **Status tiles** show the backlog (To verify, Unlinked, Conflicts, Verified) and filter
  on click.
- **Match confidence** is computed and shown as a small bars-plus-word meter
  (Strong / Weak / None) — never colour alone. Sort or filter by it.
- **Bulk bar:** select rows (or "select all that match this filter") and act once —
  e.g. *Verify and link 38 strong*, or for items *Accept suggested owner*. This turns a
  212-row backlog into a few clicks instead of 212 trips through a panel.
- **Inspector** keeps the careful single-record path for weak matches and conflicts: the
  same radio-group of candidates, the same safety check ("exists, is active, is free"),
  the same audit reason field already used on item ownership.

The two existing flows become two tabs of this workspace. The per-reseller customer-links
table stays available on the reseller detail page, but points here for bulk work.

See `mappings-workspace.mock.html`.

---

## How the design meets universal design principles

The design system already encodes most accessibility rules; the redesign extends them to
the new patterns.

| Principle | How the redesign applies it |
|---|---|
| **Equitable use** | One experience for keyboard, pointer and screen-reader users: real `<button>`, `<a>`, `<input>`, `<table>`, `role="radiogroup"`, `aria-pressed` on tiles, `aria-sort` on columns, `aria-selected` on the open row. |
| **Flexibility in use** | Three ways to the same result: click a status tile, type in search, or work row by row in the inspector. Bulk for the fast path, inspector for the careful one. |
| **Simple and intuitive** | The identical five-part frame everywhere. Plain, active, sentence-case copy. The identifier is always first and mono. |
| **Perceptible information** | Every status carries a **word + glyph**, every confidence a **bars + word** — no color-only meaning. Text 4.5:1, controls 3:1, in light and dark. |
| **Tolerance for error** | Test-before-save on connections; "exists, active, free" check before linking; an audit reason on ownership changes; "orders already placed keep their ERP". Destructive actions (Unlink, Revoke) use the danger button and stay single-step. |
| **Low physical effort** | Bulk actions collapse hundreds of interactions into one. Tiles jump straight to the backlog that matters. 32px targets, sticky inspector. |
| **Size and space** | 32px rows and controls, visible 2px focus ring with 2px offset, horizontal scroll instead of shrinking type, generous click targets on tiles. |

It also keeps the hard product rules: these are **operator-only** screens, so ERP names
and IDs are allowed here and must never leak to resellers; lifecycle and status wording
is used exactly; sample data stays fictional.

---

## Open questions before building

1. **"ERP mapping" scope** — I read it as customer links + item ownership. Is there a
   third mapping you have in mind (e.g. item code ↔ ERP SKU, or field-level mapping)?
2. **Bulk auto-link policy** — is it acceptable to let an operator verify-and-link all
   *strong* matches in one action, or must every link be reviewed individually?
3. **Connection detail** as its own route vs. an inspector drawer on the list — preference?
4. Do you want these promoted into the real `screens/*.dc.html` (and the new `.x-`
   patterns into `bundle.css` as proper components), or kept as proposals for now?

I did not modify any existing screen. Say the word and I'll turn the approved parts into
real screens and shared components.
