"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { NuqsAdapter } from "nuqs/adapters/next/app";
import { useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
	const [queryClient] = useState(() => new QueryClient());
	return (
		<QueryClientProvider client={queryClient}>
			<NuqsAdapter>
				<ThemeProvider attribute="class" disableTransitionOnChange>
					{children}
				</ThemeProvider>
			</NuqsAdapter>
		</QueryClientProvider>
	);
}
