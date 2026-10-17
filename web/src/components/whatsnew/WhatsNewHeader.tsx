import { GitHubIcon } from "@/components/common/icons/GitHubIcon";
import { TelegramIcon } from "@/components/common/icons/TelegramIcon";

export function WhatsNewHeader() {
	return (
		<div className="mt-2 mb-3 flex flex-col items-center justify-center text-center gap-2">
			<p className="text-sm text-foreground-muted mt-1">
				🔔 Get notified via the{" "}
				<a
					href="https://t.me/awesome_morphe"
					target="_blank"
					className="font-semibold text-primary hover:underline"
					rel="noopener"
				>
					<TelegramIcon className="inline size-4.5 mr-1 align-[-2px] shrink-0" />
					Telegram channel
				</a>{" "}
				whenever there's a new update.
			</p>
			<p className="text-sm text-foreground-muted">
				🔍 Explore all Morphe resources and community projects on the{" "}
				<a
					href="https://github.com/nvbangg/awesome-morphe"
					target="_blank"
					className="font-semibold text-primary hover:underline"
					rel="noopener"
				>
					<GitHubIcon className="inline size-4 text-foreground ml-1 mr-1 align-[-2px] shrink-0" />
					GitHub repository.
				</a>
			</p>
		</div>
	);
}
