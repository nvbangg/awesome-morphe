import re

IMAGE_SIZE_PIXELS = 128


def _set_query_param(url: str, pattern: str, param: str) -> str:
    updated_url, replacement_count = re.subn(pattern, rf"\1{param}", url)
    if replacement_count:
        return updated_url
    return f"{url}&{param}" if "?" in url else f"{url}?{param}"


def normalize_image_url(url: object) -> str:
    if not isinstance(url, str):
        return ""
    if "googleusercontent.com" in url or "ggpht.com" in url:
        return re.sub(r"=(?:s|w)\d+.*$", "", url) + f"=s{IMAGE_SIZE_PIXELS}-rw"
    if "avatars.githubusercontent.com" in url or "gravatar.com" in url:
        return _set_query_param(url, r"([?&])(?:size|s)=\d+", f"s={IMAGE_SIZE_PIXELS}")
    if "gitlab.com" in url:
        return _set_query_param(url, r"([?&])width=\d+", f"width={IMAGE_SIZE_PIXELS}")
    return url
