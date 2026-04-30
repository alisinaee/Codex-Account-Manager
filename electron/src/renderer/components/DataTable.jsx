import React from "react";

function DataTable({
  columns,
  sort,
  onSort,
  rows,
  rowKey,
  rowClassName,
  onRowClick,
  rowAriaLabel,
  emptyState,
  className = "",
  tableRef,
}) {
  const hasRows = Array.isArray(rows) && rows.length > 0;
  const rowClickable = typeof onRowClick === "function";

  return (
    <table ref={tableRef} className={className}>
      <colgroup>
        {columns.map((column) => (
          <col
            key={`col-${column.key}`}
            data-col={column.key}
            className={column.colClassName || ""}
            style={column.width ? { width: column.width } : undefined}
          />
        ))}
      </colgroup>
      <thead>
        <tr>
          {columns.map((column) => (
            <th
              key={column.key}
              data-col={column.key}
              className={[
                column.colClassName || "",
                column.sortable ? `sortable ${sort?.key === column.key ? "sorted" : ""}` : "",
              ].filter(Boolean).join(" ")}
              onClick={column.sortable ? () => onSort?.(column.key) : undefined}
              title={column.title}
            >
              {column.label}
              {column.sortable ? (
                <span className="sort-indicator" aria-hidden="true">
                  {sort?.key === column.key ? (sort?.dir === "asc" ? "↑" : "↓") : "↑↓"}
                </span>
              ) : null}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {hasRows ? rows.map((row) => (
          <tr
            key={rowKey(row)}
            data-row-key={rowKey(row)}
            className={[
              rowClassName?.(row) || "",
              rowClickable ? "table-row-clickable" : "",
            ].filter(Boolean).join(" ")}
            onClick={(event) => {
              if (!rowClickable) return;
              if (event.target instanceof Element && event.target.closest("button, a, input, select, textarea, label, [data-no-row-open='true']")) {
                return;
              }
              onRowClick(row, event);
            }}
            onKeyDown={(event) => {
              if (!rowClickable) return;
              if (event.target instanceof Element && event.target.closest("button, a, input, select, textarea, label, [data-no-row-open='true']") && event.target !== event.currentTarget) {
                return;
              }
              if (event.key !== "Enter" && event.key !== " ") return;
              event.preventDefault();
              onRowClick(row, event);
            }}
            tabIndex={rowClickable ? 0 : undefined}
            role={rowClickable ? "button" : undefined}
            aria-label={rowClickable
              ? (typeof rowAriaLabel === "function" ? rowAriaLabel(row) : rowAriaLabel || "Open details")
              : undefined}
          >
            {columns.map((column) => (
              <td
                key={`${rowKey(row)}-${column.key}`}
                data-col={column.key}
                className={[
                  column.colClassName || "",
                  column.className || "",
                ].filter(Boolean).join(" ")}
              >
                {column.render(row)}
              </td>
            ))}
          </tr>
        )) : (
          <tr>
            <td colSpan={columns.length}>{emptyState || "No rows"}</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}

export default DataTable;
