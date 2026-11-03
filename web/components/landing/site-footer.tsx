import { PageContainer } from "@/components/page-container";
import { FOOTER_LINK_GROUPS, SOCIAL_LINKS } from "@/lib/landing/content";
import type { FooterLinkGroup as FooterLinkGroupData, SocialLink } from "@/lib/landing/types";

import { BrandMark } from "./brand-mark";
import { FooterLinkGroup } from "./footer-link-group";
import { NewsletterForm } from "./newsletter-form";
import { SocialLinks } from "./social-links";

type SiteFooterProps = {
  groups?: readonly FooterLinkGroupData[];
  socialLinks?: readonly SocialLink[];
};

/**
 * Forest-green footer: brand and social links, three link groups, then the newsletter.
 * Focus rings switch to sand here, because the brand green fails 3:1 on this surface.
 */
export function SiteFooter({ groups = FOOTER_LINK_GROUPS, socialLinks = SOCIAL_LINKS }: SiteFooterProps) {
  return (
    <footer className="bg-brand-strong text-fg-inverse [&_:focus-visible]:outline-accent">
      <PageContainer className="grid grid-cols-2 gap-x-6 gap-y-10 py-14 lg:grid-cols-[1.6fr_1fr_1fr_1fr_1.6fr] lg:gap-8">
        <div className="col-span-2 grid content-start justify-items-start gap-4 lg:col-span-1">
          <BrandMark tone="dark" />
          <p className="max-w-xs text-sm leading-normal text-fg-inverse/80">
            Your trusted platform to buy, rent, invest in, and manage real estate.
          </p>
          <SocialLinks links={socialLinks} />
        </div>
        {groups.map((group) => (
          <FooterLinkGroup key={group.heading} group={group} />
        ))}
        <div className="col-span-2 grid content-start gap-3 lg:col-span-1">
          <h2 className="text-base font-bold">Stay in the loop</h2>
          <p className="text-sm leading-normal text-fg-inverse/80">
            Get property updates and investment opportunities.
          </p>
          <NewsletterForm />
        </div>
      </PageContainer>
      <div className="border-t border-fg-inverse/15">
        <PageContainer className="py-5 text-sm text-fg-inverse/80">
          © {new Date().getFullYear()} EstateHub. All rights reserved.
        </PageContainer>
      </div>
    </footer>
  );
}
