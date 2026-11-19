"""Publish one finished ZIP as a verified asset in the private deliveries repository."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


REPO = "bao270026-sys/deliveries"


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
        alias = Path(directory) / "openvam.zip"
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
        raise ValueError("The remote asset did not match the original ZIP's size and SHA-256.")
    return asset


def publish(path):
    size = path.stat().st_size
    if path.suffix.lower() != ".zip" or not 0 < size < 2**31 or not zipfile.is_zipfile(path):
        raise ValueError("Expected a complete ZIP file smaller than 2 GiB.")
    with path.open("rb") as stream:
        sha256 = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha256.update(chunk)
    digest = "sha256:" + sha256.hexdigest()
    tag = "openvam-" + sha256.hexdigest()
    if api("").get("private") is not True:
        raise ValueError("The delivery repository must be private.")

    existing = release(tag)
    if existing is None:
        gh("release", "create", tag, "--repo", REPO, "--target", "main", "--draft",
           "--title", path.name, "--notes", digest)
        existing = release(tag)
    if existing is None:
        raise RuntimeError("The release could not be read back.")
    asset_path = f"/releases/{existing['databaseId']}/assets"
    assets = api(asset_path)
    if not assets and existing["isDraft"]:
        upload(path, tag)
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
    parser.add_argument("zip_file", type=Path)
    try:
        print(json.dumps(publish(parser.parse_args().zip_file.resolve()), ensure_ascii=False))
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"Release delivery failed: {exc}\n")
