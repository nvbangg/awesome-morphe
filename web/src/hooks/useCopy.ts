import { useCallback, useEffect, useRef, useState } from "react";
import { UI_COPY_TIMEOUT_MS } from "@/constants";

export function useCopy() {
	const [copiedIdentifier, setCopiedIdentifier] = useState<string | null>(null);
	const timeoutRef = useRef<number | null>(null);

	const copyToClipboard = useCallback(
		async (textToCopy: string, customIdentifier?: string) => {
			if (!textToCopy) return;

			const activeIdentifier = customIdentifier || textToCopy;

			try {
				await navigator.clipboard.writeText(textToCopy);
				setCopiedIdentifier(activeIdentifier);

				if (timeoutRef.current) {
					clearTimeout(timeoutRef.current);
				}

				timeoutRef.current = window.setTimeout(() => {
					setCopiedIdentifier(null);
					timeoutRef.current = null;
				}, UI_COPY_TIMEOUT_MS);
			} catch (copyError) {
				console.error("Failed to copy text to clipboard:", copyError);
			}
		},
		[],
	);

	useEffect(() => {
		return () => {
			if (timeoutRef.current) {
				clearTimeout(timeoutRef.current);
			}
		};
	}, []);

	return { copiedText: copiedIdentifier, copyToClipboard };
}
