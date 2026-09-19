import { GitHubIcon } from "@/components/common/icons/GitHubIcon";
import { ThemeToggle } from "./ThemeToggle";

export function Header() {
  return (
    <nav className="sticky top-0 z-50 bg-background-translucent backdrop-blur-md border-b border-divider transition-shadow h-16">
      <div className="container mx-auto px-6 max-w-300 h-full flex items-center justify-between">
        <div className="flex items-center gap-3 shrink-0">
          <a
            href="https://awesome-morphe.vercel.app/"
            className="no-underline shrink-0 flex items-center hover:opacity-85 transition-opacity"
          >
            <img
              alt=""
              aria-hidden="true"
              className="size-9 object-contain select-none"
              src="assets/favicon.svg"
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
            <span className="hidden lg:block text-xs text-foreground-muted font-normal leading-tight mt-0.5">
              Explore all patch bundles from the{" "}
              <a
                href="https://morphe.software/"
                target="_blank"
                className="font-semibold bg-primary-gradient bg-clip-text text-transparent no-underline hover:opacity-80 transition-opacity"
              >
                Morphe
              </a>{" "}
              community
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <ThemeToggle />

          <a
            href="https://github.com/nvbangg/awesome-morphe"
            target="_blank"
            title="Awesome Morphe Repository"
            className="inline-flex items-center justify-center h-9 w-9 md:w-auto md:px-3 rounded-lg font-semibold text-xs gap-1.5 transition-all bg-card hover:bg-divider text-foreground border border-divider no-underline shrink-0 select-none active:scale-95"
          >
            <GitHubIcon className="size-4 shrink-0" />
            <span className="hidden md:inline">GitHub</span>
          </a>
        </div>
      </div>
    </nav>
  );
}
