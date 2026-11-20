"""Validate a stable GitHub download link without logging in or fetching a second full copy."""

import http.client
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener


REPO = "bao270026-sys/deliveries"
REPO_ID = 1463720445
PREFIX_SIZE = 1024
HEADERS = {"User-Agent": "deliveries-link-check", "Accept-Encoding": "identity"}


class AnonymousDownloadError(RuntimeError):
    """The upload can exist even though the public link has not passed its check."""


def report_delivery(receipt, local_file):
    """Report an uploaded file separately from the public download check."""
    try:
        verify_public_download(receipt, local_file)
    except AnonymousDownloadError as error:
        print(json.dumps({**receipt, "anonymous_download": "unverified"}, ensure_ascii=False, indent=2))
        print(f"Upload verified. Anonymous download still needs verification: {error}", file=sys.stderr)
        return 2
    print(json.dumps({**receipt, "anonymous_download": "verified"}, ensure_ascii=False, indent=2))
    return 0


def verify_public_download(receipt, local_file):
    """Check visibility, length and the first 1 KiB. Raises AnonymousDownloadError on failure."""
    url = receipt.get("download_url") or receipt.get("url") or ""
    address = urlsplit(url)
    if (address.scheme != "https" or address.query or address.fragment or not (
        address.netloc == "github.com" and address.path.startswith(("/" + REPO + "/raw/", "/" + REPO + "/releases/download/"))
        or address.netloc == "raw.githubusercontent.com" and address.path.startswith("/" + REPO + "/")
    )):
        raise AnonymousDownloadError("Expected a permanent GitHub download URL for the deliveries repository.")
    size = receipt["bytes"]
    path = Path(local_file)
    try:
        if type(size) is not int or size < 0 or path.stat().st_size != size:
            raise AnonymousDownloadError("The local file size differs from the upload receipt.")
        with path.open("rb") as source:
            prefix = source.read(min(size, PREFIX_SIZE))
    except OSError:
        raise AnonymousDownloadError("The local file could not be read for comparison.") from None

    # No browser cookies, gh tokens, netrc, or origin authentication handlers.
    opener = build_opener()
    meta = Request("https://api.github.com/repos/" + REPO, headers=HEADERS)
    file = Request(url, headers=HEADERS)
    if prefix:
        file.add_header("Range", f"bytes=0-{len(prefix) - 1}")

    for attempt in range(3):
        try:
            # A managed HTTPS proxy may add credentials. Check GitHub's own visibility field.
            with opener.open(meta, timeout=15) as response:
                repository = json.load(response)
            if repository.get("id") != REPO_ID or repository.get("private") is not False:
                raise AnonymousDownloadError("GitHub has not confirmed public visibility for this repository.")
            with opener.open(file, timeout=20) as response:
                if response.status == 206 and prefix:
                    wanted = f"bytes 0-{len(prefix) - 1}/{size}"
                    matches = response.headers.get("Content-Range") == wanted and response.read(len(prefix) + 1) == prefix
                elif response.status == 200:
                    length = response.headers.get("Content-Length")
                    matches = (length == str(size) or (size == 0 and length is None))
                    matches = matches and response.read(len(prefix) or 1) == prefix
                else:
                    matches = False
            if not matches:
                raise AnonymousDownloadError("The public response did not match the uploaded file size and prefix.")
            return
        except HTTPError as error:
            code = error.code
            error.close()
            detail = f"HTTP {code}"
            if code not in (404, 408, 425, 429, 500, 502, 503, 504):
                break
        except (OSError, URLError, http.client.HTTPException) as error:
            detail = type(error).__name__
        except (ValueError, AttributeError):
            raise AnonymousDownloadError("GitHub returned unreadable public repository metadata.") from None
        if attempt < 2:
            time.sleep(2 ** attempt)
    # HTTP errors and transport exceptions can contain a signed redirect URL.
    raise AnonymousDownloadError("The anonymous GitHub check failed: " + detail) from None
