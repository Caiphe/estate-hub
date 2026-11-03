import { PageContainer } from "@/components/page-container";
import { HEADER_ACTIONS } from "@/lib/landing/navigation";

import { ActionLink } from "./action-link";
import { BrandMark } from "./brand-mark";
import { MobileMenu } from "./mobile-menu";
import { PrimaryNavigation } from "./primary-navigation";

/** Transparent and absolutely placed so the hero's wash shows behind it. */
export function SiteHeader({ currentHref }: { currentHref?: string }) {
  return (
    <header className="absolute inset-x-0 top-0 z-10">
      <PageContainer className="flex min-h-(--site-header-height) items-center justify-between gap-8">
        <BrandMark />
        <PrimaryNavigation currentHref={currentHref} className="hidden lg:block" />
        <div className="hidden gap-3 lg:flex">
          <ActionLink href={HEADER_ACTIONS.logIn.href} variant="secondary">
            {HEADER_ACTIONS.logIn.label}
          </ActionLink>
          <ActionLink href={HEADER_ACTIONS.getStarted.href} variant="primary">
            {HEADER_ACTIONS.getStarted.label}
          </ActionLink>
        </div>
        <MobileMenu currentHref={currentHref} />
      </PageContainer>
    </header>
  );
}
