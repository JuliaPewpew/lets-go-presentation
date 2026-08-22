import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "let’s go! — бот для общих приключений",
  description: "Превращаем «когда-нибудь надо» в ваши общие воспоминания.",
  openGraph: {
    title: "let’s go! — бот для общих приключений",
    description: "Из «когда-нибудь» — в воспоминания.",
    images: [{ url: "/og.png", width: 1672, height: 941, alt: "let’s go!" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "let’s go! — бот для общих приключений",
    description: "Из «когда-нибудь» — в воспоминания.",
    images: ["/og.png"],
  },
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="ru"><body>{children}</body></html>; }
