export default function HomePage() {
  return (
    <main className="landing">
      <p className="eyebrow">EstateHub</p>
      <h1>Property, connected.</h1>
      <p className="summary">
        The EstateHub foundation is running. Property discovery and staff workflows will be
        delivered in the next milestones.
      </p>
      <a className="button-link" href="/login">
        Staff sign in
      </a>
      <a className="button-link" href="http://localhost:8000/docs">
        Open API documentation
      </a>
    </main>
  );
}
