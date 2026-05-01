import React from "react";

function DataTable({
  columns,
  sort,
  onSort,
  onColumnResize,
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
  const resizeStateRef = React.useRef(null);

  React.useEffect(() => () => {
    document.body.classList.remove("column-resize-active");
  }, []);

  const stopColumnResize = React.useCallback(() => {
    resizeStateRef.current = null;
    document.body.classList.remove("column-resize-active");
  }, []);

  const handlePointerMove = React.useCallback((event) => {
    const state = resizeStateRef.current;
    if (!state) {
      return;
    }
    const nextWidthPx = state.startWidth + (event.clientX - state.startX);
    const clamped = Math.max(state.minWidth, Math.min(state.maxWidth, Math.round(nextWidthPx)));
    onColumnResize?.(state.key, `${clamped}px`, { commit: false });
  }, [onColumnResize]);

  const handlePointerUp = React.useCallback((event) => {
    const state = resizeStateRef.current;
    if (!state) {
      return;
    }
    const nextWidthPx = state.startWidth + (event.clientX - state.startX);
    const clamped = Math.max(state.minWidth, Math.min(state.maxWidth, Math.round(nextWidthPx)));
    onColumnResize?.(state.key, `${clamped}px`, { commit: true });
    stopColumnResize();
  }, [onColumnResize, stopColumnResize]);

  React.useEffect(() => {
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", stopColumnResize);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", stopColumnResize);
    };
  }, [handlePointerMove, handlePointerUp, stopColumnResize]);

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
                column.resizable ? "resizable" : "",
                column.sortable ? `sortable ${sort?.key === column.key ? "sorted" : ""}` : "",
              ].filter(Boolean).join(" ")}
              onClick={column.sortable ? () => onSort?.(column.key) : undefined}
              title={column.title}
            >
              <span className="table-header-label">
                {column.label}
                {column.sortable ? (
                  <span className="sort-indicator" aria-hidden="true">
                    {sort?.key === column.key ? (sort?.dir === "asc" ? "↑" : "↓") : "↑↓"}
                  </span>
                ) : null}
              </span>
              {column.resizable ? (
                <button
                  type="button"
                  className="column-resize-handle"
                  data-col-resize-handle={column.key}
                  aria-label={`Resize ${column.label} column`}
                  title={`Resize ${column.label} column`}
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                  }}
                  onPointerDown={(event) => {
                    if (!(event.currentTarget instanceof HTMLElement)) {
                      return;
                    }
                    const header = event.currentTarget.closest("th");
                    if (!(header instanceof HTMLElement)) {
                      return;
                    }
                    event.preventDefault();
                    event.stopPropagation();
                    resizeStateRef.current = {
                      key: column.key,
                      startX: event.clientX,
                      startWidth: Math.round(header.getBoundingClientRect().width),
                      minWidth: Number.isFinite(Number(column.resizeMinWidth)) ? Number(column.resizeMinWidth) : 72,
                      maxWidth: Number.isFinite(Number(column.resizeMaxWidth)) ? Number(column.resizeMaxWidth) : 640,
                    };
                    document.body.classList.add("column-resize-active");
                  }}
                />
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
