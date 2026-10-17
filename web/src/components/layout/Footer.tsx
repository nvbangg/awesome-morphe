import { ArrowUp } from "lucide-react";
import { useEffect, useState } from "react";

export function Footer() {
	const [isScrollTopVisible, setIsScrollTopVisible] = useState(false);

	useEffect(() => {
		const handleScroll = () => {
			setIsScrollTopVisible(window.scrollY > 400);
		};
		window.addEventListener("scroll", handleScroll, { passive: true });
		return () => window.removeEventListener("scroll", handleScroll);
	}, []);

	return (
		<>
			<footer className="mt-4 border-t border-divider bg-background pt-4 pb-20 sm:pb-6">
				<div className="container mx-auto px-6 max-w-300 flex flex-col gap-3">
					<div className="flex items-center gap-3 w-fit">
						<a
							href="https://awesome-morphe.vercel.app/"
							className="no-underline shrink-0 flex items-center hover:opacity-85 transition-opacity"
						>
							<img
								alt="Awesome Morphe home"
								className="size-9 object-contain select-none"
								src="assets/favicon.svg"
								loading="lazy"
								decoding="async"
							/>
						</a>
						<div className="flex flex-col justify-center">
							<a
								href="https://awesome-morphe.vercel.app/"
								className="font-bold text-lg leading-tight no-underline hover:opacity-85 transition-opacity"
							>
								<span className="bg-primary-gradient bg-clip-text text-transparent">
									Awesome
								</span>{" "}
								<span className="text-foreground">Morphe</span>
							</a>
							<span className="text-xs text-foreground-muted font-normal leading-tight mt-0.5">
								Explore all patch bundles from the{" "}
								<a
									href="https://morphe.software/"
									target="_blank"
									className="font-semibold bg-primary-gradient bg-clip-text text-transparent no-underline hover:opacity-80 transition-opacity"
									rel="noopener"
								>
									Morphe
								</a>{" "}
								community
							</span>
						</div>
					</div>
					<div className="border-t border-divider pt-3 text-foreground-muted text-xs leading-relaxed flex flex-col gap-1.5">
						<p>
							<a
								href="https://github.com/nvbangg/awesome-morphe"
								target="_blank"
								className="font-semibold text-primary no-underline hover:opacity-80 transition-opacity"
								rel="noopener"
							>
								This project
							</a>{" "}
							is not affiliated with{" "}
							<a
								href="https://morphe.software/"
								target="_blank"
								className="font-semibold text-primary no-underline hover:opacity-80 transition-opacity"
								rel="noopener"
							>
								Morphe
							</a>{" "}
							or any authors mentioned here.
						</p>
						<p>
							Only use patch sources or projects you trust. This project is for
							informational purposes only and is not responsible for any arising
							issues.
						</p>
					</div>
				</div>
			</footer>

			<button
				type="button"
				aria-label="Scroll to top"
				onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
				className={`fixed bottom-6 right-6 z-50 size-12 rounded-full shadow-xl transition-all duration-300 bg-primary text-background dark:text-foreground flex items-center justify-center border-none cursor-pointer hover:opacity-90 active:scale-95 ${isScrollTopVisible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-4 pointer-events-none"}`}
			>
				<ArrowUp className="size-6" />
			</button>
		</>
	);
}
