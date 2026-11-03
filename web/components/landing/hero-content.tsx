/** Badge, page-level heading, and supporting copy. Line breaks come from width, not `<br>`. */
export function HeroContent() {
  return (
    <div className="hero-content">
      <p className="badge-pill">Real estate, simplified</p>
      <h1 id="hero-heading" className="hero-title">
        Find, invest, and manage properties with <span className="hero-title-brand">EstateHub</span>
      </h1>
      <p className="hero-lead">
        A modern platform to discover properties, invest with confidence, and manage your real
        estate portfolio all in one place.
      </p>
    </div>
  );
}
