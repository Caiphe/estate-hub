import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { ASSET_REQUIREMENTS, LANDING_ASSETS, type ManifestEntry } from "./assets";

const entries: [string, ManifestEntry][] = Object.entries(LANDING_ASSETS);

/** Reads width and height from a PNG's IHDR chunk. */
function pngSize(path: string): { width: number; height: number } {
  const header = readFileSync(path);
  expect(header.subarray(1, 4).toString("ascii")).toBe("PNG");
  return { width: header.readUInt32BE(16), height: header.readUInt32BE(20) };
}

describe("landing asset manifest", () => {
  it.each(entries)("%s has intentional alt text", (_key, entry) => {
    expect(entry.alt).toBe(entry.alt.trim());
    if (entry.slot === "investmentBanner") {
      expect(entry.alt).toBe("");
    } else {
      expect(entry.alt.length).toBeGreaterThan(10);
    }
  });

  it("labels placeholder images as placeholders", () => {
    for (const [, entry] of entries.filter(([, e]) => e.status === "placeholder")) {
      if (entry.alt) expect(entry.alt).toMatch(/^Image placeholder for /);
    }
  });

  // Vitest resolves large imported images to a root-relative path; Next resolves them to
  // StaticImageData. Only final assets are checked: placeholders are vector stand-ins.
  it.each(entries.filter(([, e]) => e.status === "final"))(
    "%s meets its slot's size and aspect requirements",
    (_key, entry) => {
      expect(typeof entry.src).toBe("string");
      const { width, height } = pngSize(join(process.cwd(), entry.src as string));
      const required = ASSET_REQUIREMENTS[entry.slot];

      expect(width).toBeGreaterThanOrEqual(required.minWidth);
      expect(height).toBeGreaterThanOrEqual(required.minHeight);
      expect(Math.abs(width / height - required.aspectRatio)).toBeLessThan(0.05);
    },
  );
});
