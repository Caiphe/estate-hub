import type { NextConfig } from "next";

// The browser calls the API on the web origin (/api/v1/...), and Next.js forwards those
// requests to the API service. Auth cookies therefore belong to the web origin, where
// proxy.ts can see them, and no CORS is involved. Evaluated when the server starts (dev)
// or at build time (production image).
const apiTarget = (process.env.INTERNAL_API_BASE_URL ?? "http://localhost:8000/api/v1").replace(
  /\/+$/,
  "",
);

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  // Development only: Playwright and some tools browse via 127.0.0.1 rather than localhost.
  allowedDevOrigins: ["127.0.0.1"],
  turbopack: {
    root: process.cwd(),
  },
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${apiTarget}/:path*` }];
  },
};

export default nextConfig;
