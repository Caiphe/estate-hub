/**
 * Loading stand-in with the card's geometry (16:9 image, title, location, price, facts),
 * so swapping in real cards does not shift the grid. Hidden from assistive technology;
 * the section announces loading once instead.
 */
export function PropertyCardSkeleton() {
  return (
    <div
      aria-hidden="true"
      className="flex h-full flex-col overflow-hidden rounded-md border border-line bg-surface shadow-card"
    >
      <div className="aspect-video bg-surface-tint motion-safe:animate-pulse" />
      <div className="flex flex-1 flex-col gap-3 p-5 *:rounded-sm *:bg-surface-tint motion-safe:*:animate-pulse">
        <div className="h-6 w-3/4" />
        <div className="h-4 w-1/2" />
        <div className="h-7 w-2/5" />
        <div className="mt-auto h-4 w-4/5" />
      </div>
    </div>
  );
}
