import type { Metadata } from "next";

import { postLoginPath } from "@/lib/auth/redirect";

import { LoginForm } from "./login-form";

export const metadata: Metadata = {
  title: "Sign in",
  robots: { index: false, follow: false },
};

type LoginPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const params = await searchParams;
  const next = typeof params.next === "string" ? params.next : null;

  return (
    <main className="auth-page">
      <section className="panel auth-panel" aria-labelledby="login-heading">
        <p className="eyebrow">EstateHub staff</p>
        <h1 id="login-heading" className="page-title">
          Sign in
        </h1>
        <LoginForm
          redirectTo={postLoginPath(next)}
          passwordChanged={params.changed === "1"}
        />
      </section>
    </main>
  );
}
