import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  align?: "left" | "right";
  render: (row: T) => ReactNode;
  /** Value to compare when this column is sorted. Omit to leave the column unsortable
   * (e.g. a column backed by its own per-row fetch, or a pure actions column). */
  sortValue?: (row: T) => string | number | null | undefined;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  emptyMessage?: string;
  isLoading?: boolean;
  onRowClick?: (row: T) => void;
  rowClassName?: (row: T) => string | undefined;
  /** Rows per page. Omit to disable pagination (short/fixed lists don't need it). */
  pageSize?: number;
}

const SKELETON_ROWS = 4;

function compare(a: string | number | null | undefined, b: string | number | null | undefined): number {
  if (a == null && b == null) return 0;
  if (a == null) return -1;
  if (b == null) return 1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/** design/design-system/components/DataTable.md — .erp-table from bundle.css. Generic
 * over the row type so every list screen (orders, connections, bindings, items) shares
 * one table implementation instead of hand-rolling markup per screen. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  emptyMessage = "No data",
  isLoading,
  onRowClick,
  rowClassName,
  pageSize,
}: DataTableProps<T>) {
  const showSkeleton = isLoading && rows.length === 0;
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);

  const sortColumn = sort ? columns.find((c) => c.key === sort.key) : undefined;
  const sortedRows = useMemo(() => {
    if (!sort || !sortColumn?.sortValue) return rows;
    const { sortValue } = sortColumn;
    const dir = sort.dir;
    return [...rows].sort((a, b) => compare(sortValue(a), sortValue(b)) * dir);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, sort, sortColumn]);

  const pageCount = pageSize ? Math.max(1, Math.ceil(sortedRows.length / pageSize)) : 1;
  const clampedPage = Math.min(page, pageCount - 1);

  // A new filter/search/sort can shrink or reorder the row count out from under the
  // current page.
  useEffect(() => {
    if (page > pageCount - 1) setPage(Math.max(0, pageCount - 1));
  }, [page, pageCount]);

  const visibleRows = pageSize ? sortedRows.slice(clampedPage * pageSize, clampedPage * pageSize + pageSize) : sortedRows;

  function toggleSort(key: string) {
    setPage(0);
    setSort((prev) => {
      if (prev?.key !== key) return { key, dir: 1 };
      return prev.dir === 1 ? { key, dir: -1 } : null;
    });
  }

  return (
    <div className="erp-table-wrap">
      <table className="erp-table">
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key;
              const ariaSort = active ? (sort!.dir === 1 ? "ascending" : "descending") : c.sortValue ? "none" : undefined;
              return (
                <th key={c.key} className={c.align === "right" ? "num" : undefined} aria-sort={ariaSort}>
                  {c.sortValue ? (
                    // A <span role="button">, not a real <button> — a column header can
                    // carry its own interactive content (e.g. an InfoTag), which HTML
                    // disallows nesting inside an actual <button>.
                    <span
                      className="erp-th-sort"
                      role="button"
                      tabIndex={0}
                      onClick={() => toggleSort(c.key)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          toggleSort(c.key);
                        }
                      }}
                    >
                      {c.header}
                    </span>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {showSkeleton ? (
            Array.from({ length: SKELETON_ROWS }, (_, i) => (
              <tr key={`skeleton-${i}`} aria-hidden="true">
                {columns.map((c) => (
                  <td key={c.key} className={c.align === "right" ? "num" : undefined}>
                    <span className="erp-skeleton" style={{ width: c.align === "right" ? 40 : "70%" }} />
                  </td>
                ))}
              </tr>
            ))
          ) : rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="muted">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            visibleRows.map((row) => (
              <tr
                key={rowKey(row)}
                className={rowClassName?.(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                style={onRowClick ? { cursor: "pointer" } : undefined}
              >
                {columns.map((c) => (
                  <td key={c.key} className={c.align === "right" ? "num" : undefined}>
                    {c.render(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
      {pageSize && sortedRows.length > pageSize && (
        <div className="pager">
          <span>
            {clampedPage * pageSize + 1}–{Math.min(sortedRows.length, (clampedPage + 1) * pageSize)} of {sortedRows.length}
          </span>
          <div className="pager__nav">
            <button
              type="button"
              className="icon-btn"
              aria-label="Previous page"
              disabled={clampedPage === 0}
              onClick={() => setPage(clampedPage - 1)}
            >
              <ChevronLeft size={16} strokeWidth={2} />
            </button>
            <span>
              Page {clampedPage + 1} of {pageCount}
            </span>
            <button
              type="button"
              className="icon-btn"
              aria-label="Next page"
              disabled={clampedPage >= pageCount - 1}
              onClick={() => setPage(clampedPage + 1)}
            >
              <ChevronRight size={16} strokeWidth={2} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
