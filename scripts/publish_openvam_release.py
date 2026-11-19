"""Publish a finished file as one verified asset in the deliveries repository."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile
import zlib


REPO = "bao270026-sys/deliveries"
REPO_ID = 1463720445


def gh(*args, cwd=None, missing_ok=False):
    result = subprocess.run(
        ["gh", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", env={**os.environ, "GH_PROMPT_DISABLED": "1", "GH_HOST": "github.com"},
    )
    if result.returncode:
        message = result.stderr.strip()
        if missing_ok and message.lower().endswith("release not found"):
            return None
        raise RuntimeError(message or f"gh exited with status {result.returncode}")
    return result.stdout


def api(path):
    return json.loads(gh("api", "--hostname", "github.com", f"repos/{REPO}{path}"))


def release(tag):
    raw = gh("release", "view", tag, "--repo", REPO, "--json", "databaseId,isDraft",
             missing_ok=True)
    return json.loads(raw) if raw is not None else None


def upload(path, tag):
    # A label makes gh treat the filename literally, including glob characters.
    def send(directory, name):
        gh("release", "upload", tag, "--repo", REPO, "--",
           f"./{name}#{path.name}", cwd=directory)

    if "#" not in path.name:
        send(path.parent, path.name)
        return
    # gh reserves '#' for asset labels. Stage an alias for that input only.
    with tempfile.TemporaryDirectory() as directory:
        alias = Path(directory) / ("delivery" + path.suffix.replace("#", "_"))
        try:
            os.link(path, alias)
        except OSError:
            shutil.copyfile(path, alias)
        send(directory, alias.name)


def verified_asset(assets, size, digest):
    if len(assets) != 1:
        raise ValueError("Expected exactly one release asset. Preserved the existing release.")
    asset = assets[0]
    if (asset.get("state"), asset.get("size"), asset.get("digest")) != ("uploaded", size, digest):
        raise ValueError("The remote asset did not match the original file's size and SHA-256.")
    return asset


def publish(path):
    path = path.resolve(strict=True)
    if not path.is_file() or any(ord(char) < 32 or ord(char) == 127 for char in path.name):
        raise ValueError("Expected a regular file with a single-line filename.")
    size = path.stat().st_size
    if size >= 2**31:
        raise ValueError("GitHub requires each release asset to be smaller than 2 GiB.")
    is_zip = path.suffix.lower() == ".zip"
    if is_zip:
        try:
            with zipfile.ZipFile(path) as archive:
                if archive.testzip() is not None:
                    raise ValueError("The ZIP failed CRC verification.")
        except (zipfile.BadZipFile, EOFError, zlib.error) as exc:
            raise ValueError("The ZIP failed its integrity check.") from exc
    with path.open("rb") as stream:
        sha256 = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha256.update(chunk)
    digest = "sha256:" + sha256.hexdigest()
    tag = ("openvam-" if is_zip else "delivery-") + sha256.hexdigest()
    if api("").get("id") != REPO_ID:
        raise ValueError("GitHub returned a different repository ID for the delivery destination.")

    existing = release(tag)
    if existing is None:
        gh("release", "create", tag, "--repo", REPO, "--target", "main", "--draft",
           "--title", path.name, "--notes", f"原始文件名：{path.name}\n{digest}")
        existing = release(tag)
    if existing is None:
        raise RuntimeError("The release could not be read back.")
    asset_path = f"/releases/{existing['databaseId']}/assets"
    assets = api(asset_path)
    if not assets and existing["isDraft"]:
        try:
            upload(path, tag)
        except RuntimeError:
            # A lost upload response can follow a successful transfer.
            if not api(asset_path):
                raise
        assets = api(asset_path)
    asset = verified_asset(assets, size, digest)
    if existing["isDraft"]:
        gh("release", "edit", tag, "--repo", REPO, "--draft=false", "--latest=false")
        published = release(tag)
        if not published or published["isDraft"] or published["databaseId"] != existing["databaseId"]:
            raise ValueError("The verified release has not been published.")
        asset = verified_asset(api(asset_path), size, digest)
    return {"url": asset["browser_download_url"], "bytes": size, "sha256": sha256.hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    try:
        print(json.dumps(publish(parser.parse_args().file), ensure_ascii=False))
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"Release delivery failed: {exc}\n")
