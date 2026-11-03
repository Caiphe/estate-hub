import Link from "next/link";

import { PageContainer } from "@/components/page-container";
import { HEADER_ACTIONS } from "@/lib/landing/navigation";

import { BrandMark } from "./brand-mark";
import { PrimaryNavigation } from "./primary-navigation";

export function SiteHeader({ currentHref }: { currentHref?: string }) {
  return (
    <header className="site-header">
      <PageContainer className="site-header-inner">
        <BrandMark />
        <PrimaryNavigation currentHref={currentHref} />
        <div className="site-header-actions">
          <Link href={HEADER_ACTIONS.logIn.href} className="action action-secondary">
            {HEADER_ACTIONS.logIn.label}
          </Link>
          <Link href={HEADER_ACTIONS.getStarted.href} className="action action-primary">
            {HEADER_ACTIONS.getStarted.label}
          </Link>
        </div>
      </PageContainer>
    </header>
  );
}
