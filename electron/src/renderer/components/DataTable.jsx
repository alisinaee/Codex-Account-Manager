import React from "react";

function DataTable({
  columns,
  sort,
  onSort,
  rows,
  rowKey,
  rowClassName,
  emptyState,
  className = "",
}) {
  const hasRows = Array.isArray(rows) && rows.length > 0;

  return (
    <table className={className}>
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
          <tr key={rowKey(row)} className={rowClassName?.(row)}>
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
