"use client";

import { CustomModal } from "@/components/common/CustomModal";
import { AppDetail } from "./AppDetail";
import { useCatalog } from "./api";
import { BundleDetail } from "./BundleDetail";
import { useCatalogParams } from "./params";

export function CatalogDialog({ isWhatsNew }: { isWhatsNew: boolean }) {
	const { data } = useCatalog();
	const [params, setParams] = useCatalogParams();
	const app =
		data && Object.hasOwn(data.appPatchesMap, params.app) ? params.app : "";
	const bundleKey = params.github
		? `github:${params.github}`
		: params.gitlab
			? `gitlab:${params.gitlab}`
			: "";
	const bundle =
		data && Object.hasOwn(data.bundleMap, bundleKey.toLowerCase())
			? bundleKey
			: "";
	const close = () => setParams({ app: "", github: "", gitlab: "", patch: "" });
	if (!data || params["test-bundle"] !== null) return null;
	return (
		<CustomModal
			isOpen={Boolean(app || bundle)}
			onClose={close}
			label={
				app
					? (data.namesMap[app]?.name ?? app)
					: (data.bundleMap[bundle.toLowerCase()]?.name ?? "Details")
			}
		>
			{app ? (
				<AppDetail
					key={app}
					packageName={app}
					activeData={data}
					searchQuery={params.patch}
					onSearchChange={(patch) => setParams({ patch })}
					isWhatsNew={isWhatsNew}
				/>
			) : bundle ? (
				<BundleDetail
					key={bundle}
					bundleKey={bundle}
					activeData={data}
					searchQuery={params.patch}
					onSearchChange={(patch) => setParams({ patch })}
					isWhatsNew={isWhatsNew}
				/>
			) : null}
		</CustomModal>
	);
}
