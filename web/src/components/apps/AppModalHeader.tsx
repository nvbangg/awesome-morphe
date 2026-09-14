import { Badge } from "@/components/common/Badge";
import { GooglePlayButton } from "@/components/common/ActionButtons";
import { PackageNameCopy } from "@/components/common/PackageNameCopy";
import { AppAvatar } from "@/components/common/ItemAvatar";
import { ModalHeader, CloseButton } from "@/components/common/CustomModal";
import { isNew } from "@/utils/formatters";
import { AppMeta } from "@/utils";
import {
  PACKAGE_UNIVERSAL,
  CATEGORY_LABEL_UNIVERSAL,
  MIN_DISPLAY_INSTALLS,
} from "@/constants";

interface AppModalHeaderProps {
  appMeta: AppMeta;
  packageName: string | null;
  copiedText: string | null;
  copyToClipboard: (text: string) => void;
  onClose: () => void;
}

export function AppModalHeader({
  appMeta,
  packageName,
  copiedText,
  copyToClipboard,
  onClose,
}: AppModalHeaderProps) {
  const showGooglePlay =
    packageName !== PACKAGE_UNIVERSAL &&
    appMeta.category !== CATEGORY_LABEL_UNIVERSAL;

  return (
    <ModalHeader>
      <div className="flex flex-row items-start justify-between gap-4 w-full">
        <div className="flex flex-row items-center gap-4 flex-1 min-w-0">
          <AppAvatar src={appMeta.appIcon} size="lg" />
          <div className="flex flex-col min-w-0 justify-center">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-xl font-bold tracking-tight text-foreground truncate">
                {appMeta.appName}
              </h2>
              {isNew(appMeta.firstSeen) && <Badge variant="new" />}
              {appMeta.isPreRelease && <Badge variant="prerelease" />}
              {showGooglePlay &&
                appMeta.minInstalls !== undefined &&
                appMeta.minInstalls >= MIN_DISPLAY_INSTALLS && (
                  <Badge variant="downloads" value={appMeta.minInstalls} />
                )}
            </div>
            <PackageNameCopy
              packageName={packageName || undefined}
              copiedText={copiedText}
              copyToClipboard={copyToClipboard}
            />
          </div>
        </div>

        <div className="hidden sm:flex items-center gap-2 shrink-0">
          {appMeta.category && (
            <Badge variant="category">{appMeta.category}</Badge>
          )}
          {showGooglePlay && packageName && (
            <GooglePlayButton packageName={packageName} />
          )}
          <CloseButton onClose={onClose} />
        </div>

        <div className="sm:hidden shrink-0">
          <CloseButton onClose={onClose} />
        </div>
      </div>

      {appMeta.description && (
        <p className="text-sm text-foreground-muted leading-relaxed wrap-break-word">
          {appMeta.description}
        </p>
      )}

      <div className="flex sm:hidden items-center justify-between gap-3 mt-1 w-full">
        {appMeta.category && (
          <Badge variant="category">{appMeta.category}</Badge>
        )}
        {showGooglePlay && packageName && (
          <GooglePlayButton packageName={packageName} className="shrink-0" />
        )}
      </div>
    </ModalHeader>
  );
}
