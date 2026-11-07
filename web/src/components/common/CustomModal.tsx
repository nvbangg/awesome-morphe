import { Dialog } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import { useRef } from "react";

interface CustomModalProps {
	isOpen: boolean;
	onClose: () => void;
	children: React.ReactNode;
	maxWidth?: string;
	centerMobile?: boolean;
	label?: string;
	focusPopup?: boolean;
}

export function CustomModal({
	isOpen,
	onClose,
	children,
	maxWidth = "max-w-205",
	centerMobile = false,
	label = "Details",
	focusPopup = false,
}: CustomModalProps) {
	const popupRef = useRef<HTMLDivElement>(null);

	return (
		<Dialog.Root
			open={isOpen}
			onOpenChange={(open) => {
				if (!open) onClose();
			}}
		>
			<Dialog.Portal>
				<Dialog.Viewport
					className={`fixed inset-0 z-50 bg-overlay backdrop-blur-sm flex items-center justify-center ${centerMobile ? "p-4" : "p-4 max-sm:p-0"}`}
				>
					<Dialog.Popup
						ref={popupRef}
						initialFocus={focusPopup ? popupRef : undefined}
						aria-label={label}
						aria-describedby={undefined}
						className={`relative z-10 rounded-3xl w-full ${maxWidth} overflow-hidden flex flex-col max-h-[90vh] shadow-modal bg-background border-none ${centerMobile ? "" : "max-sm:rounded-none max-sm:max-h-dvh max-sm:h-full"} outline-none duration-200 isolate transform-gpu backface-hidden`}
					>
						{children}
					</Dialog.Popup>
				</Dialog.Viewport>
			</Dialog.Portal>
		</Dialog.Root>
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

export function CloseButton() {
	return (
		<Dialog.Close
			type="button"
			aria-label="Close modal"
			className="rounded-xl shrink-0 border border-divider text-foreground-muted hover:text-foreground bg-card hover:bg-divider size-8 flex items-center justify-center transition-all cursor-pointer outline-none active:scale-95 shadow-2xs"
		>
			<X className="size-4" />
		</Dialog.Close>
	);
}
