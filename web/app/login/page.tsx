import type { Metadata } from "next";

import { MarketingPanel } from "@/components/auth/marketing-panel";
import { BrandMark } from "@/components/landing/brand-mark";
import { postLoginPath } from "@/lib/auth/redirect";

import { sourceSerif } from "./fonts";
import { LoginForm } from "./login-form";

export const metadata: Metadata = {
  title: "Log in",
  robots: { index: false, follow: false },
};

type LoginPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

/**
 * Split screen: the dusk marketing panel and a white sign-in panel. The image runs under the
 * sign-in panel's rounded leading corners, so the panel's edge stays on the column line:
 * 45/55 for tablets and compact desktops (md), giving the form its full width, and the
 * reference's 55/45 from xl. Below md a short image band stacks above the form.
 */
export default async function LoginPage({ searchParams }: LoginPageProps) {
  const params = await searchParams;
  const next = typeof params.next === "string" ? params.next : null;

  return (
    <main
      className={`site ${sourceSerif.variable} grid min-h-viewport grid-rows-[auto_1fr] bg-dusk font-sans text-base leading-normal text-fg md:grid-cols-[45fr_55fr] md:grid-rows-1 xl:grid-cols-[55fr_45fr]`}
    >
      <MarketingPanel />

      <section
        aria-labelledby="login-heading"
        className="relative -mt-6 grid content-start justify-items-center rounded-t-panel bg-surface px-(--gutter) py-12 md:mt-0 md:content-center md:rounded-none md:rounded-l-panel"
      >
        <div className="w-full max-w-form">
          {/* The mobile band above already carries the brand. */}
          <div className="hidden justify-center md:flex">
            <BrandMark size="lg" />
          </div>
          <h1 id="login-heading" className="text-display font-extrabold leading-tight tracking-tight md:mt-12 xl:mt-14">
            Welcome back
          </h1>
          <p className="mt-2 text-xl text-fg-muted">Log in to your EstateHub account</p>
          <div className="mt-8">
            <LoginForm redirectTo={postLoginPath(next)} passwordChanged={params.changed === "1"} />
          </div>
        </div>
      </section>
    </main>
  );
}
