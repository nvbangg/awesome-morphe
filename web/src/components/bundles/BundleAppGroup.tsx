import { Badge } from "@/components/common/Badge";
import { GooglePlayButton } from "@/components/common/ActionButtons";
import { PackageNameCopy } from "@/components/common/PackageNameCopy";
import { AppAvatar } from "@/components/common/ItemAvatar";
import { ExpandChevron } from "@/components/common/ExpandChevron";
import { PatchItemRow } from "@/components/common/PatchItemRow";
import { isNew } from "@/utils/formatters";
import { isAllPatchesPreRelease, BundleMeta } from "@/utils/domainUtils";
import { PACKAGE_UNIVERSAL } from "@/constants";
import { AppGroupData } from "@/services/queryService";

interface BundleAppGroupProps {
  group: AppGroupData;
  bundleMeta?: BundleMeta;
  isExpanded: boolean;
  toggleAppGroup: (packageName: string) => void;
  copiedText: string | null;
  copyToClipboard: (text: string) => void;
}

export function BundleAppGroup({
  group,
  bundleMeta,
  isExpanded,
  toggleAppGroup,
  copiedText,
  copyToClipboard,
}: BundleAppGroupProps) {
  const showGooglePlay = group.packageName !== PACKAGE_UNIVERSAL;

  const isBundleNew = Boolean(bundleMeta && isNew(bundleMeta.firstSeen));
  const isBundlePreRelease = Boolean(bundleMeta?.isPreRelease);

  const isAppNew =
    !isBundleNew &&
    Boolean(bundleMeta && isNew(bundleMeta.appFirstSeen?.[group.packageName]));
  const isAppPreRelease =
    !isBundlePreRelease && isAllPatchesPreRelease(group.patches);

  const hidePatchPreReleaseBadge = isBundlePreRelease || isAppPreRelease;
  const hidePatchNewBadge = isBundleNew || isAppNew;

  const patchBadge = <Badge variant="patches" value={group.totalPatchCount} />;

  return (
    <div className="border border-divider rounded-xl bg-card flex flex-col">
      <div
        onClick={() => toggleAppGroup(group.packageName)}
        className={`flex flex-col gap-2 px-4 py-3 bg-card cursor-pointer rounded-t-xl ${isExpanded ? "border-b border-divider shadow-sm" : "rounded-b-xl"}`}
      >
        <div className="flex items-center justify-between gap-3 w-full">
          <AppAvatar src={group.appMeta.appIcon} />

          <div className="flex-1 min-w-0 flex flex-col justify-center">
            <div className="flex items-center gap-2 min-w-0 flex-wrap">
              <div className="font-bold text-foreground text-sm truncate">
                {group.appMeta.appName}
              </div>
              {isAppNew && <Badge variant="new" />}
              {isAppPreRelease && <Badge variant="prerelease" />}
            </div>
            <PackageNameCopy
              packageName={group.packageName}
              copiedText={copiedText}
              copyToClipboard={copyToClipboard}
            />
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {showGooglePlay ? (
              <div className="hidden sm:flex items-center gap-2">
                {patchBadge}
                <GooglePlayButton packageName={group.packageName} size="sm" />
              </div>
            ) : (
              patchBadge
            )}
            <ExpandChevron
              isExpanded={isExpanded}
              className="hidden sm:inline-flex"
            />
          </div>
        </div>

        {showGooglePlay && (
          <div className="sm:hidden flex items-center justify-between gap-2 pt-1">
            {patchBadge}
            <GooglePlayButton packageName={group.packageName} size="sm" />
          </div>
        )}
      </div>

      {isExpanded && (
        <div className="flex flex-col max-h-[50dvh] overflow-y-auto pr-1">
          {group.patches.map((patchItem) => (
            <PatchItemRow
              key={patchItem.id}
              patchItem={patchItem}
              copiedText={copiedText}
              copyToClipboard={copyToClipboard}
              hidePreReleaseBadge={hidePatchPreReleaseBadge}
              hideNewBadge={hidePatchNewBadge}
            />
          ))}
        </div>
      )}
    </div>
  );
}
