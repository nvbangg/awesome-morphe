import { X } from "lucide-react";
import { useEffect } from "react";

interface CustomModalProps {
	isOpen: boolean;
	onClose: () => void;
	children: React.ReactNode;
	maxWidth?: string;
	centerMobile?: boolean;
}

export function CustomModal({
	isOpen,
	onClose,
	children,
	maxWidth = "max-w-205",
	centerMobile = false,
}: CustomModalProps) {
	useEffect(() => {
		if (!isOpen) return;

		document.body.style.overflow = "hidden";

		const handleEscape = (e: KeyboardEvent) => {
			if (e.key === "Escape") {
				onClose();
			}
		};
		document.addEventListener("keydown", handleEscape);

		return () => {
			document.body.style.overflow = "";
			document.removeEventListener("keydown", handleEscape);
		};
	}, [isOpen, onClose]);

	if (!isOpen) return null;

	return (
		<div
			className={`fixed inset-0 z-50 bg-overlay backdrop-blur-sm flex items-center justify-center ${centerMobile ? "p-4" : "p-4 max-sm:p-0"} animate-in fade-in duration-200`}
		>
			<button
				type="button"
				aria-label="Close modal"
				onClick={onClose}
				className="absolute inset-0 cursor-pointer"
			/>
			<div
				className={`relative z-10 rounded-3xl w-full ${maxWidth} overflow-hidden flex flex-col max-h-[90vh] shadow-modal bg-background border-none ${centerMobile ? "" : "max-sm:rounded-none max-sm:max-h-dvh max-sm:h-full"} outline-none animate-in zoom-in-95 duration-200 isolate transform-gpu backface-hidden`}
			>
				{children}
			</div>
		</div>
	);
}

interface ModalHeaderProps {
	children: React.ReactNode;
	className?: string;
}

export function ModalHeader({ children, className = "" }: ModalHeaderProps) {
	return (
		<div
			className={`px-3.5 sm:px-6 pt-5 pb-3 border-b border-divider flex flex-col gap-3 sticky top-0 bg-background-translucent backdrop-blur-xl z-20 shrink-0 ${className}`}
		>
			{children}
		</div>
	);
}

interface ModalBodyProps {
	children: React.ReactNode;
	className?: string;
}

export function ModalBody({ children, className = "" }: ModalBodyProps) {
	return (
		<div
			className={`px-2.5 sm:px-6 pb-5 pt-3 flex flex-col gap-3 overflow-y-auto flex-1 min-h-0 bg-background ${className}`}
		>
			{children}
		</div>
	);
}

interface CloseButtonProps {
	onClose: () => void;
}

export function CloseButton({ onClose }: CloseButtonProps) {
	return (
		<button
			type="button"
			onClick={onClose}
			aria-label="Close modal"
			className="rounded-xl shrink-0 border border-divider text-foreground-muted hover:text-foreground bg-card hover:bg-divider size-8 flex items-center justify-center transition-all cursor-pointer outline-none active:scale-95 shadow-2xs"
		>
			<X className="size-4" />
		</button>
	);
}
