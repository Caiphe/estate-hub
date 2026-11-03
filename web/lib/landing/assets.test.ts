import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { ASSET_REQUIREMENTS, LANDING_ASSETS, type ManifestEntry } from "./assets";

const entries: [string, ManifestEntry][] = Object.entries(LANDING_ASSETS);

/** Reads pixel dimensions from a PNG IHDR chunk or a JPEG start-of-frame marker. */
function imageSize(path: string): { width: number; height: number } {
  const bytes = readFileSync(path);
  if (bytes.subarray(1, 4).toString("ascii") === "PNG") {
    return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
  }
  expect(bytes.readUInt16BE(0)).toBe(0xffd8); // JPEG
  for (let offset = 2; offset < bytes.length; offset += 2 + bytes.readUInt16BE(offset + 2)) {
    const marker = bytes.readUInt16BE(offset);
    // SOF0–SOF15, excluding DHT (C4), JPG (C8), and DAC (CC).
    if (marker >= 0xffc0 && marker <= 0xffcf && ![0xffc4, 0xffc8, 0xffcc].includes(marker)) {
      return { height: bytes.readUInt16BE(offset + 5), width: bytes.readUInt16BE(offset + 7) };
    }
  }
  throw new Error(`No image dimensions found in ${path}`);
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
      const { width, height } = imageSize(join(process.cwd(), entry.src as string));
      const required = ASSET_REQUIREMENTS[entry.slot];

      expect(width).toBeGreaterThanOrEqual(required.minWidth);
      expect(height).toBeGreaterThanOrEqual(required.minHeight);
      expect(Math.abs(width / height - required.aspectRatio)).toBeLessThan(0.05);
    },
  );
});
