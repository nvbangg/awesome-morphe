"use client";

import { useQuery } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { useState } from "react";
import { useCatalog } from "@/features/catalog/api";
import { setTestBundle, useCatalogParams } from "@/features/catalog/params";
import { fetchTestBundle, parseRepository } from "./api";

const TestBundleInputModal = dynamic(() =>
	import("./TestBundleInputModal").then(
		(module) => module.TestBundleInputModal,
	),
);
const TestBundleViewModal = dynamic(() =>
	import("./TestBundleViewModal").then((module) => module.TestBundleViewModal),
);

export function TestBundleController() {
	const { data: catalog } = useCatalog();
	const [params] = useCatalogParams();
	const [inputError, setInputError] = useState("");
	const isOpen = params["test-bundle"] !== null;
	const link = params.github
		? `https://github.com/${params.github}`
		: params.gitlab
			? `https://gitlab.com/${params.gitlab}`
			: "";
	const query = useQuery({
		queryKey: ["test-bundle", link],
		queryFn: ({ signal }) => fetchTestBundle(link, signal),
		enabled: isOpen && Boolean(link),
		retry: false,
		refetchOnWindowFocus: false,
		refetchOnReconnect: false,
	});
	const close = () => {
		setInputError("");
		setTestBundle(null);
	};
	const hasPreview = query.isSuccess && !query.isFetching;
	if (!isOpen || !catalog) return null;
	return (
		<>
			<TestBundleInputModal
				isOpen={!hasPreview}
				onClose={close}
				isLoading={query.isFetching}
				error={inputError || query.error?.message || ""}
				onSubmit={async (value) => {
					try {
						const repository = parseRepository(value);
						setInputError("");
						if (repository.repoUrl === link) await query.refetch();
						else setTestBundle(repository);
					} catch (error) {
						setInputError(
							error instanceof Error
								? error.message
								: "Invalid repository URL.",
						);
					}
				}}
			/>
			<TestBundleViewModal
				isOpen={hasPreview}
				data={query.data ?? null}
				activeData={catalog}
				onClose={close}
			/>
		</>
	);
}
