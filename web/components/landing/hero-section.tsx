import type { ReactNode } from "react";

import { PageContainer } from "@/components/page-container";

import { HeroContent } from "./hero-content";
import { HeroMedia } from "./hero-media";

/**
 * Left copy, right photograph, on the pale wash the header sits over. Below desktop the
 * photograph follows the copy and search instead. At desktop the search slot keeps a
 * minimum height, so the hero's size does not depend on the panel.
 */
export function HeroSection({ search }: { search?: ReactNode }) {
  return (
    <section
      aria-labelledby="hero-heading"
      className="relative overflow-hidden bg-surface-tint pt-[calc(var(--site-header-height)+--spacing(6))] lg:pb-12"
    >
      <PageContainer className="relative z-1 grid gap-8">
        <HeroContent />
        <div className="lg:min-h-44">{search}</div>
      </PageContainer>
      <HeroMedia />
    </section>
  );
}
