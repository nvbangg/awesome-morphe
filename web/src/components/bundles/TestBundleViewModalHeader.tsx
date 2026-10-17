import { AddToMorpheButton } from "@/components/common/ActionButtons";
import { CloseButton, ModalHeader } from "@/components/common/CustomModal";

interface TestBundleViewModalHeaderProps {
	repoUrl: string;
	branches: string[];
	availableBranches: string[];
	currentBranch: string;
	setCurrentBranch: (branch: string) => void;
	deepLink: string;
	onClose: () => void;
}

export function TestBundleViewModalHeader({
	repoUrl,
	branches,
	availableBranches,
	currentBranch,
	setCurrentBranch,
	deepLink,
	onClose,
}: TestBundleViewModalHeaderProps) {
	return (
		<ModalHeader>
			<div className="flex flex-col gap-3 w-full">
				<div className="flex items-center justify-between gap-4 w-full">
					<a
						href={repoUrl}
						target="_blank"
						className="text-lg font-bold text-primary hover:underline dark:text-secondary break-all whitespace-normal"
						rel="noopener"
					>
						{repoUrl}
					</a>
					<CloseButton onClose={onClose} />
				</div>

				<div className="flex items-center justify-between gap-3 flex-wrap">
					<div className="flex items-center gap-1 bg-card p-1 rounded-xl border border-divider">
						{branches.map((branch) => {
							const isAvailable = availableBranches.includes(branch);
							return (
								<button
									key={branch}
									type="button"
									disabled={!isAvailable}
									onClick={() => isAvailable && setCurrentBranch(branch)}
									className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
										currentBranch === branch
											? "bg-primary text-background dark:text-foreground shadow-xs"
											: isAvailable
												? "text-foreground-muted hover:text-foreground cursor-pointer"
												: "text-foreground-subtle opacity-50 cursor-not-allowed"
									}`}
								>
									{branch}
								</button>
							);
						})}
					</div>

					<AddToMorpheButton deepLink={deepLink} />
				</div>
			</div>
		</ModalHeader>
	);
}
