import type { Metadata } from "next";
import type { ReactNode } from "react";

import { manrope } from "@/lib/fonts";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "EstateHub",
    template: "%s | EstateHub",
  },
  description: "Property sales, lettings, and management.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" className={manrope.variable}>
      <body>{children}</body>
    </html>
  );
}
