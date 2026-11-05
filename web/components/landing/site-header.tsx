import { PageContainer } from "@/components/page-container";
import { HEADER_ACTIONS } from "@/lib/landing/navigation";

import { AccountLink } from "./account-link";
import { ActionLink } from "./action-link";
import { BrandMark } from "./brand-mark";
import { MobileMenu } from "./mobile-menu";
import { PrimaryNavigation } from "./primary-navigation";

/**
 * Transparent and absolutely placed so the hero's wash shows behind it.
 *
 * `signedIn` (a session cookie is present) swaps "Log in" for a profile icon that links to
 * the workspace. The icon stays visible on small screens, beside the menu button.
 */
export function SiteHeader({
  currentHref,
  signedIn = false,
}: {
  currentHref?: string;
  signedIn?: boolean;
}) {
  return (
    <header className="absolute inset-x-0 top-0 z-10">
      <PageContainer className="flex min-h-(--site-header-height) items-center justify-between gap-8">
        <BrandMark />
        <PrimaryNavigation
          currentHref={currentHref}
          className="hidden lg:block"
        />
        <div className="flex items-center gap-3">
          <div className="hidden gap-3 lg:flex">
            {signedIn ? null : (
              <ActionLink href={HEADER_ACTIONS.logIn.href} variant="secondary">
                {HEADER_ACTIONS.logIn.label}
              </ActionLink>
            )}
            <ActionLink href={HEADER_ACTIONS.getStarted.href} variant="primary">
              {HEADER_ACTIONS.getStarted.label}
            </ActionLink>
          </div>
          {signedIn ? <AccountLink /> : null}
          <MobileMenu currentHref={currentHref} signedIn={signedIn} />
        </div>
      </PageContainer>
    </header>
  );
}
