"use client";

export function Pagination({
  total,
  offset,
  count,
  pageSize,
  label,
  onPage,
}: {
  total: number;
  offset: number;
  count: number;
  pageSize: number;
  label: string;
  onPage: (offset: number) => void;
}) {
  const start = total === 0 ? 0 : offset + 1;
  return (
    <nav className="pagination" aria-label={label}>
      <p aria-live="polite">
        Showing {start}–{offset + count} of {total}
      </p>
      <div className="inline">
        <button
          type="button"
          className="button button-secondary"
          disabled={offset === 0}
          onClick={() => onPage(Math.max(0, offset - pageSize))}
        >
          Previous
        </button>
        <button
          type="button"
          className="button button-secondary"
          disabled={offset + count >= total}
          onClick={() => onPage(offset + pageSize)}
        >
          Next
        </button>
      </div>
    </nav>
  );
}
