# UI Design - ERP & Supply Chain Order Portal

Screen designs and design system for the reseller portal and the operator admin. Use these as the source of truth for UI work in Functional Design, Application Design and Code Generation.

**Status**: Proposed designs, generated from `aidlc-docs/inception/requirements/requirements.md`. Sample data is fictional. Behavior marked *proposed* below is not yet in the requirements.

**2026-10-15 update**: ERP connections and ERP mapping have since been built and shipped,
and diverged from `proposals/` in ways worth knowing before reusing these mocks — see the
status note at the top of `proposals/README.md`. The current source of truth for those two
screens is `aidlc-docs/construction/U4-admin/functional-design/frontend-components.md`; the
component-level rules below (badge roles, button variants, density, accessibility) are
still followed by the real implementation.

**Original canvas** (private, needs sharing to open): https://claude.ai/artifact/6eBqj5D5HxF6heLE2DKkqy
**Design system**: https://claude.ai/artifact/NpEvLYzy99C4C1ishLaM4d

## Folder layout

```
design/
  README.md                     this file
  design-system/
    README.md                   usage rules for the design system
    components/*.md             guidelines: Button, StatusBadge, DataTable, OrderTimeline
  screens/
    *.dc.html                   the ten screens (see inventory)
    ui.css                      shared layout classes (built only from tokens)
    ds/erpportal/
      tokens.css                compiled design tokens, light and dark
      tokens.json               token source, with a usage note per token
      components/bundle.css     component classes: erp-btn, erp-badge, erp-table, erp-timeline
```

## How to read the `.dc.html` files

They were authored in Claude Design's component format. Read them as markup plus CSS:
- `<x-dc>`, `<helmet>`, `<sc-for>`, `{{ }}` and the `<script type="text/x-dc">` block belong to that editor. In these files they only set the theme and render the sidebar links. Ignore them when implementing.
- Everything else is plain HTML using the CSS classes in `ui.css` and `bundle.css` and the CSS variables in `tokens.css`. Table rows are literal markup, so a row shows the intended cell content and status.
- Implement in React by translating the markup one to one, keeping the class names or mapping them to your styling approach, and taking every color, spacing and radius from the tokens. Do not introduce new hex values.
- The mocks load IBM Plex from Google Fonts. In the product, self-host the fonts (SECURITY-04 and SECURITY-13).

## Screen inventory

Routes are proposed.

| File | Route | Audience | Requirements | Shows |
|---|---|---|---|---|
| `Main.dc.html` | `/orders` | Reseller | FR-34 | Order list, status counts, attention notice, filters, table |
| `OrderDetail.dc.html` | `/orders/:orderId` | Reseller | FR-12 to FR-15, FR-34 | Lines, details, timeline with Retrying state, deliveries for this order |
| `DeliveryLog.dc.html` | `/deliveries` | Reseller | FR-33, FR-34 | Delivery table, detail panel with attempts, payload, replay |
| `WebhookEndpoints.dc.html` | `/webhooks` | Reseller | FR-32, FR-34 | Endpoint list, add form, one-time signing secret, signature verification help |
| `AdminTenants.dc.html` | `/admin/resellers` | Operator | FR-35, FR-37 | Reseller list, status, customer-link state |
| `AdminTenantDetail.dc.html` | `/admin/resellers/:tenantId` | Operator | FR-20, FR-21, FR-37 | Customer links per ERP connection, link-and-verify flow, API client |
| `AdminConnections.dc.html` | `/admin/connections` | Operator | FR-26, FR-35 | Connection health, queue, settings, recent errors |
| `AdminItemOwnership.dc.html` | `/admin/items/ownership` | Operator | FR-10, FR-22 | Item ownership conflicts and resolution |
| `AdminFailedMessages.dc.html` | `/admin/failed-messages` | Operator | FR-29, FR-30, FR-19 | Retrying, rejected and dead-lettered messages, raw error beside the reseller-safe message |
| `AdminAudit.dc.html` | `/admin/audit` | Operator | FR-38 | Audit trail with before and after values |

## Rules that must hold

- **No ERP identity on reseller screens (FR-19, AC-02).** Reseller screens, errors, webhook payloads and the delivery log never show an ERP name, instance or ERP record ID. Only the operator screens do. Keep the two apps' data models separate so a reseller view cannot leak these fields.
- **Lifecycle words are exact:** Draft, Submitted, Validated, Sent to ERP, Confirmed, Fulfilled, Closed. Exceptions: Retrying and Rejected. Open item O-07 asks whether "Sent to ERP" may be shown to resellers.
- **Status badge roles:** neutral (Draft, Closed, Paused), progress (Submitted, Validated, Sent to ERP, Onboarding), success (Confirmed, Fulfilled, Delivered, Active, Verified), warning (Retrying, To verify, Needs owner, Slow), danger (Rejected, Failed, Unreachable, Dead-lettered). Every badge has a word and a glyph.
- **Copy:** plain, active, sentence case. Errors say what happened and what to do. No emoji or exclamation marks.
- **Data text:** set order numbers, reference numbers, IDs and timestamps in the mono style (`.id`, `.mono`). Use tabular numerals in number columns and right-align them.
- **Accessibility:** text 4.5:1, control borders 3:1 in both themes, a solid 2px focus ring, real `<label>`, `<button>`, `<a>`, `<input>` elements, no color-only meaning.
- **Density:** table rows and buttons are 32px. Panels use a 1px border and no shadow; shadow is for menus and dialogs only.
- **Themes:** light and dark come from `data-theme` on a container. Both must work.

## Gaps for the next design steps

- **Missing components in the design system:** input, select, checkbox, radio, tabs, callout, panel, stat tile, list, code block. They exist only as CSS in `screens/ui.css`. Promote them into shared components when implementing.
- **Not designed:** sign in, the new-order form and its line editor, the item catalog, the mapping viewer or editor, user management, and empty, loading and error states. Design these following the rules above and ask the user before deviating from an existing screen.
- **Proposed behavior not yet in the requirements:** the webhook signature header format and five-minute replay window, the 24-hour overlap when rotating a secret, the event names (`order.created`, `order.status_changed`, `order.retrying`, `order.rejected`), pausing a reseller, revoking a client, and exports. Confirm before treating as requirements (see O-08).
