import type { Metadata } from "next";
import Script from "next/script";
import { Suspense } from "react";
import { Footer } from "@/components/layout/Footer";
import { Header } from "@/components/layout/Header";
import { CatalogShell } from "@/features/catalog/CatalogShell";
import { Providers } from "./providers";
import "@/index.css";

const SITE_URL = "https://awesome-morphe.vercel.app";
const SITE_DESCRIPTION = "Explore all patch bundles from the Morphe community.";

export const metadata: Metadata = {
	metadataBase: new URL(SITE_URL),
	title: "Awesome Morphe Website",
	description: SITE_DESCRIPTION,
	icons: { icon: "/assets/favicon.svg" },
	manifest: "/site.webmanifest",
	openGraph: {
		title: "Awesome Morphe Website",
		description: SITE_DESCRIPTION,
		type: "website",
		images: [
			{
				url: "/assets/og-image.png",
				width: 1200,
				height: 630,
				alt: "Awesome Morphe Website",
			},
		],
	},
	twitter: { card: "summary_large_image" },
};

export default function RootLayout({
	children,
}: {
	children: React.ReactNode;
}) {
	return (
		<html lang="en" className="scroll-smooth" suppressHydrationWarning>
			<body>
				<script type="application/ld+json">
					{JSON.stringify({
						"@context": "https://schema.org",
						"@type": "WebSite",
						name: "Awesome Morphe Website",
						url: SITE_URL,
						description: SITE_DESCRIPTION,
					})}
				</script>
				<Providers>
					<div className="min-h-screen bg-background text-foreground transition-colors duration-300">
						<Header />
						<Suspense>
							<CatalogShell>{children}</CatalogShell>
						</Suspense>
						<Footer />
					</div>
				</Providers>
				<Script src="https://www.googletagmanager.com/gtag/js?id=G-80G574QRZ0" />
				<Script id="google-tag">{`window.dataLayer = window.dataLayer || []; function gtag(){dataLayer.push(arguments);} gtag('js', new Date()); gtag('config', 'G-80G574QRZ0');`}</Script>
			</body>
		</html>
	);
}
