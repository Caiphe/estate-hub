"use client";

import { useCallback } from "react";
import type { CSSProperties } from "react";

import { PageContainer } from "@/components/page-container";
import { VALUE_PROPOSITIONS } from "@/lib/landing/content";
import type { ValueProposition } from "@/lib/landing/types";

import { IconTile } from "./icon-tile";

type ValuePropositionStripProps = {
  items?: readonly ValueProposition[];
};

/**
 * Reassurance strip under the hero. Desktop: four columns with hairline separators.
 * Smaller screens: icon beside text, one or two columns.
 */
export function ValuePropositionStrip({ items = VALUE_PROPOSITIONS }: ValuePropositionStripProps) {
  const revealRef = useCallback((list: HTMLUListElement | null) => {
    if (
      !list ||
      !("IntersectionObserver" in window) ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      return;
    }

    // The attribute is added only when motion is supported, so the content stays visible
    // without JavaScript, IntersectionObserver, or when reduced motion is requested.
    list.dataset.motion = "pending";
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        list.dataset.motion = "entered";
        observer.disconnect();
      },
      { rootMargin: "0px 0px -8%", threshold: 0.18 },
    );
    observer.observe(list);

    return () => observer.disconnect();
  }, []);

  return (
    <section aria-labelledby="value-strip-heading">
      <PageContainer>
        <h2 id="value-strip-heading" className="sr-only">
          Why EstateHub
        </h2>
        <ul
          ref={revealRef}
          className="value-proposition-list relative grid gap-6 border-b border-line py-8 sm:grid-cols-2 lg:grid-cols-4 lg:gap-0"
        >
          {items.map((item, index) => (
            <li
              key={item.id}
              className="value-proposition-item flex items-start gap-4 border-line lg:flex-col lg:gap-3 lg:px-6 lg:not-first:border-l"
              style={{ "--value-delay": `${index * 105}ms` } as CSSProperties}
            >
              <div className="value-proposition-icon">
                <IconTile name={item.icon} />
              </div>
              <div className="value-proposition-copy">
                <h3 className="text-base leading-snug font-bold">{item.title}</h3>
                <p className="text-sm leading-snug text-fg-muted">{item.description}</p>
              </div>
            </li>
          ))}
        </ul>
      </PageContainer>
    </section>
  );
}
