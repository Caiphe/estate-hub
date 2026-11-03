/** Badge, page-level heading, and supporting copy. Line breaks come from width, not `<br>`. */
export function HeroContent() {
  return (
    <div className="grid max-w-hero-copy justify-items-start gap-5">
      <p className="rounded-full bg-brand-subtle px-3 py-1 text-sm font-semibold text-brand-strong">
        Real estate, simplified
      </p>
      <h1
        id="hero-heading"
        className="max-w-headline text-display leading-tight font-extrabold tracking-tight"
      >
        Find, invest, and manage properties{" "}
        {/* Keeps "with EstateHub" together so no width strands the name on its own line. */}
        <span className="whitespace-nowrap">
          with <span className="text-brand">EstateHub</span>
        </span>
      </h1>
      <p className="max-w-measure text-lg leading-normal">
        A modern platform to discover properties, invest with confidence, and manage your real
        estate portfolio all in one place.
      </p>
    </div>
  );
}
