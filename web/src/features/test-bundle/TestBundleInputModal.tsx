import { Loader2 } from "lucide-react";
import { useState } from "react";
import { CustomModal, ModalBody } from "@/components/common/CustomModal";
import { SearchInput } from "@/components/common/SearchInput";

interface TestBundleInputModalProps {
	isOpen: boolean;
	onClose: () => void;
	onSubmit: (link: string) => void;
	isLoading?: boolean;
	error?: string;
}

export function TestBundleInputModal({
	isOpen,
	onClose,
	onSubmit,
	isLoading,
	error,
}: TestBundleInputModalProps) {
	const [link, setLink] = useState("");

	return (
		<CustomModal
			isOpen={isOpen}
			onClose={onClose}
			maxWidth="max-w-lg"
			centerMobile
		>
			<ModalBody className="pt-6">
				<form
					onSubmit={(e) => {
						e.preventDefault();
						if (link.trim() && !isLoading) {
							const targetLink = link.trim();
							setLink("");
							onSubmit(targetLink);
						}
					}}
					className="flex flex-col gap-4"
				>
					<p className="text-sm font-medium text-foreground">
						Enter a GitHub / GitLab repository URL
					</p>
					<div className="flex flex-col gap-1">
						<SearchInput
							value={link}
							onChange={setLink}
							placeholder="https://github.com/user/repo"
						/>
						{error && <p className="text-sm text-warning mt-1">{error}</p>}
					</div>

					<div className="flex justify-end gap-2 mt-2">
						<button
							type="button"
							onClick={onClose}
							className="px-4 py-2 text-sm font-semibold rounded-xl border border-divider hover:bg-divider transition-colors text-foreground cursor-pointer"
						>
							Cancel
						</button>
						<button
							type="submit"
							disabled={!link.trim() || isLoading}
							className="px-4 py-2 text-sm font-semibold rounded-xl bg-primary text-background dark:text-foreground hover:opacity-90 transition-all disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer flex items-center gap-2"
						>
							{isLoading ? (
								<>
									<Loader2 className="size-4 animate-spin shrink-0" />
									Loading...
								</>
							) : (
								"OK"
							)}
						</button>
					</div>
				</form>
			</ModalBody>
		</CustomModal>
	);
}
