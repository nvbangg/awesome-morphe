import { memo, useState } from "react";
import { RowItem, PatchOption } from "@/types/data";
import { Badge } from "@/components/common/Badge";
import { isNew } from "@/utils";
import { ExpandChevron } from "./ExpandChevron";
import { SupportedVersions } from "./SupportedVersions";

interface PatchItemRowProps {
  patchItem: RowItem;
  copiedText: string | null;
  copyToClipboard: (text: string, key?: string) => void;
  hidePreReleaseBadge?: boolean;
  hideNewBadge?: boolean;
}

const PatchOptionsGroup = memo(function PatchOptionsGroup({
  options,
}: {
  options: PatchOption[];
}) {
  return (
    <div
      onClick={(e) => e.stopPropagation()}
      className="mt-1 p-2.5 bg-card border border-divider rounded-lg flex flex-col gap-2 select-text"
    >
      {options.map((opt, idx) => (
        <div key={opt.key || idx} className="flex flex-col gap-0.5">
          <span className="text-xs font-semibold text-foreground">
            {opt.title || opt.key}
          </span>
          {opt.description && (
            <p className="text-xs text-foreground-muted leading-normal">
              {opt.description}
            </p>
          )}
        </div>
      ))}
    </div>
  );
});

export const PatchItemRow = memo(function PatchItemRow({
  patchItem,
  copiedText,
  copyToClipboard,
  hidePreReleaseBadge,
  hideNewBadge,
}: PatchItemRowProps) {
  const [showOptions, setShowOptions] = useState(false);

  const hasOptions =
    Array.isArray(patchItem.options) && patchItem.options.length > 0;
  const isDefaultOff = patchItem.default === false;

  return (
    <div
      onClick={() => {
        if (hasOptions) {
          setShowOptions((prev) => !prev);
        }
      }}
      className={`py-2.5 px-4 bg-card border-b last:border-b-0 last:rounded-b-xl border-divider flex flex-col gap-1.5 text-foreground ${hasOptions ? "cursor-pointer" : ""}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-2 gap-y-1.5 w-full">
        <div className="flex items-center gap-2 flex-wrap max-w-full">
          <span className="font-semibold text-sm text-foreground wrap-break-word select-text">
            {patchItem.patchName}
          </span>

          {!hideNewBadge && isNew(patchItem.firstSeen) && (
            <Badge variant="new" />
          )}

          {!hidePreReleaseBadge && patchItem.isPatchPreRelease && (
            <Badge variant="prerelease" />
          )}

          {isDefaultOff && <Badge variant="off" />}

          {hasOptions && (
            <span
              className="inline-flex items-center justify-center p-0.5 text-primary bg-primary/20 rounded-md border border-primary/30 hover:bg-primary/30 transition-colors shrink-0"
              title={showOptions ? "Hide patch options" : "Show patch options"}
            >
              <ExpandChevron isExpanded={showOptions} className="size-3.5!" />
            </span>
          )}
        </div>

        <SupportedVersions
          patchId={patchItem.id}
          versions={patchItem.versions}
          copiedText={copiedText}
          copyToClipboard={copyToClipboard}
        />
      </div>

      {patchItem.patchDesc && (
        <p className="text-xs text-foreground-muted leading-relaxed select-text">
          {patchItem.patchDesc}
        </p>
      )}

      {hasOptions && showOptions && (
        <PatchOptionsGroup options={patchItem.options!} />
      )}
    </div>
  );
});
