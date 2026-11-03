import type { ReactNode } from "react";

import { PageContainer } from "@/components/page-container";

import { HeroContent } from "./hero-content";
import { HeroMedia } from "./hero-media";

/**
 * Left copy, right photograph, on the pale wash the header sits over. `search` renders
 * beneath the copy; its slot keeps a minimum height so adding the panel does not resize
 * the hero.
 */
export function HeroSection({ search }: { search?: ReactNode }) {
  return (
    <section className="hero" aria-labelledby="hero-heading">
      <HeroMedia />
      <PageContainer className="hero-inner">
        <HeroContent />
        <div className="hero-search">{search}</div>
      </PageContainer>
    </section>
  );
}
