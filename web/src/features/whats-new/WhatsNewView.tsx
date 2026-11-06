"use client";

import { useQuery } from "@tanstack/react-query";
import { useCatalog } from "@/features/catalog/api";
import { getBundleParams, useCatalogParams } from "@/features/catalog/params";
import { historyQuery } from "./api";
import { WhatsNewHeader } from "./WhatsNewHeader";
import { WhatsNewList } from "./WhatsNewList";

export function WhatsNewView() {
	const { data: catalog } = useCatalog();
	const { data: history, isPending, error } = useQuery(historyQuery);
	const [, setParams] = useCatalogParams();
	if (error)
		return (
			<p role="alert" className="py-12 text-center text-warning">
				Failed to load What's New. Please try again.
			</p>
		);
	return (
		<div className="my-3">
			<WhatsNewHeader />
			<WhatsNewList
				history={history ?? []}
				isLoading={isPending}
				activeData={catalog ?? null}
				onAppClick={(app) =>
					setParams({ app, github: "", gitlab: "", patch: "" })
				}
				onBundleClick={(bundle) => setParams(getBundleParams(bundle))}
				onPatchClick={(app, patch) =>
					setParams({ app, patch, github: "", gitlab: "" })
				}
			/>
		</div>
	);
}
