import type { Metadata } from "next";
import type { ReactNode } from "react";

import { WorkspaceShell } from "@/components/workspace-shell";
import { SessionProvider } from "@/lib/session";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

/** Authenticated staff pages. proxy.ts redirects visitors without a session to /login. */
export default function WorkspaceLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <SessionProvider>
      <WorkspaceShell>{children}</WorkspaceShell>
    </SessionProvider>
  );
}
