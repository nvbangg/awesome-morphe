export const PACKAGE_UNIVERSAL = "__universal__";
export const CATEGORY_UNIVERSAL = "not-on-google-play";
export const CATEGORY_LABEL_UNIVERSAL = "Not on Google Play";
export const ITEMS_PER_PAGE = 21;
export const WHATS_NEW_DAYS_PER_PAGE = 5;
export const UI_SCROLL_ROOT_MARGIN = "400px";
export const UI_COPY_TIMEOUT_MS = 1500;
export const UI_NEW_BADGE_DAYS = 7;
export const UI_NEW_BADGE_MS = UI_NEW_BADGE_DAYS * 24 * 60 * 60 * 1000;
export const MIN_DISPLAY_INSTALLS = 100;
export const DEFAULT_TAB = "apps" as const;
export const BUNDLE_CATEGORY_OPTIONS = [
  { key: "all", label: "All categories" },
  { key: "official", label: "Official bundles" },
  { key: "unofficial", label: "Unofficial" },
];
