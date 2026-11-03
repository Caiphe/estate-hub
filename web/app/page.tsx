import { FeaturedProperties } from "@/components/landing/featured-properties";
import { HeroSection } from "@/components/landing/hero-section";
import { HowItWorks } from "@/components/landing/how-it-works";
import { InvestmentBanner } from "@/components/landing/investment-banner";
import { LandingPage } from "@/components/landing/landing-page";
import { PropertySearch } from "@/components/landing/property-search";
import { ValuePropositionStrip } from "@/components/landing/value-proposition-strip";
import { getFeaturedProperties } from "@/lib/landing/featured";
import { parseSearchQuery } from "@/lib/landing/search";

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  // Header links such as "Rent" arrive as /?listing=rent and preselect that mode.
  const [initialQuery, featured] = await Promise.all([
    searchParams.then(parseSearchQuery),
    getFeaturedProperties(),
  ]);

  return (
    <LandingPage>
      <HeroSection
        search={<PropertySearch key={initialQuery.listing} initialQuery={initialQuery} />}
      />
      <ValuePropositionStrip />
      <FeaturedProperties state={{ status: "ready", ...featured }} />
      <InvestmentBanner />
      <HowItWorks />
    </LandingPage>
  );
}
