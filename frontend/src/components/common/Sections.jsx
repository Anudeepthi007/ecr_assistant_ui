import React from "react";
import { ChevronRight } from "lucide-react";

/**
 * Plain building blocks for every page: a collapsible section, a label/value
 * table and a simple data table. Text and tables only - no charts or graphs.
 */
export function Expander({ title, note, defaultOpen = true, children }) {
  return (
    <details open={defaultOpen} className="surface group">
      <summary className="flex cursor-pointer select-none list-none items-center gap-2 px-5 py-3 text-sm font-medium [&::-webkit-details-marker]:hidden">
        <ChevronRight className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-90" />
        {title}
      </summary>
      <div className="border-t border-border/60 px-5 py-4">
        {note ? <p className="text-sm italic text-muted-foreground">{note}</p> : children}
      </div>
    </details>
  );
}

export function KeyValues({ rows }) {
  return (
    <table className="mb-3 w-full text-sm last:mb-0">
      <tbody>
        {rows.map(([label, value]) => (
          <tr key={label} className="border-t border-border/50 align-top first:border-t-0">
            <td className="w-48 py-2 pr-4 text-muted-foreground">{label}</td>
            <td className="whitespace-pre-line py-2">{value ?? "-"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * columns: [{ key, label, render?, className? }]
 */
export function DataTable({ columns, rows, rowKey, onRowClick, empty = "Nothing to show.", minWidth = 640 }) {
  if (!rows?.length) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" style={{ minWidth }}>
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            {columns.map((column) => (
              <th key={column.key} className="pb-2 pr-3 font-medium">
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr
              key={rowKey ? rowKey(row) : index}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={`border-t border-border/50 align-top ${onRowClick ? "cursor-pointer hover:bg-secondary/40" : ""}`}
            >
              {columns.map((column) => (
                <td key={column.key} className={`py-2 pr-3 ${column.className || ""}`}>
                  {column.render ? column.render(row, index) : row[column.key] ?? "-"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export const titleCase = (value) =>
  value
    ? String(value)
        .replace(/_/g, " ")
        .toLowerCase()
        .replace(/^\w/, (c) => c.toUpperCase())
    : "";
