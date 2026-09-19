import { memo } from "react";
import { Sun, Moon } from "lucide-react";
import { useTheme } from "next-themes";

export const ThemeToggle = memo(function ThemeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const isDarkMode = resolvedTheme === "dark" || theme === "dark";

  return (
    <button
      type="button"
      id="theme-toggle"
      aria-label="Toggle theme"
      onClick={() => setTheme(isDarkMode ? "light" : "dark")}
      className="inline-flex items-center justify-center h-9 w-9 md:w-auto md:px-3 rounded-full font-semibold text-xs gap-1.5 transition-all bg-card hover:bg-divider text-foreground border border-divider cursor-pointer shrink-0 select-none active:scale-95"
    >
      {isDarkMode ? (
        <>
          <Moon className="size-4 text-secondary fill-secondary shrink-0" />
          <span className="hidden md:inline">Dark</span>
        </>
      ) : (
        <>
          <Sun className="size-4 text-warning fill-warning shrink-0" />
          <span className="hidden md:inline">Light</span>
        </>
      )}
    </button>
  );
});
