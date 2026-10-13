// Real brand marks (CC0, via simple-icons) for the login screen's animated backdrop —
// ERP vendors only, not generic "ecosystem" apps. See docs/erps/README.md: Odoo is the
// only one actually registered; the rest are real ERPs we don't have an adapter for yet.
// NetSuite has no mark in simple-icons, so it renders as a text chip.
import odoo from "simple-icons/icons/odoo.svg?raw";
import sap from "simple-icons/icons/sap.svg?raw";

export interface ErpBrand {
  name: string;
  svg: string | null;
  status: "live" | "soon";
}

export const ERP_BRANDS: ErpBrand[] = [
  { name: "Odoo", svg: odoo, status: "live" },
  { name: "SAP", svg: sap, status: "soon" },
  { name: "NetSuite", svg: null, status: "soon" },
];
