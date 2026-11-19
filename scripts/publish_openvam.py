"""Publish one finished ZIP to bao270026-sys/deliveries on main, preserving its name."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote, urlsplit
import uuid
import zipfile
import zlib


REPOSITORY = "bao270026-sys/deliveries"
BRANCH = "refs/heads/main"
MAX_BYTES = 100 * 1024 * 1024
ATTEMPTS = 4


class DeliveryError(Exception):
    pass


class GitError(DeliveryError):
    def __init__(self, operation, detail):
        reason = "Git operation failed"
        hints = (
            (("authentication failed", "permission denied", "could not read username",
              "403", "write access", "repository not found"), "check repository access"),
            (("protected branch", "repository rule", "gh006", "gh013"), "repository rules rejected the update"),
            (("non-fast-forward", "fetch first", "failed to update ref", "cannot lock ref"),
             "the remote branch was updated concurrently"),
            (("could not resolve", "timed out", "connection", "remote end hung up"),
             "network connection failed"),
            (("couldn't find remote ref",), "the main branch was not found"),
        )
        lower = detail.lower()
        for patterns, explanation in hints:
            if any(pattern in lower for pattern in patterns):
                reason = explanation
                break
        # Git error messages can contain an authenticated proxy URL.
        super().__init__(f"{operation}: {reason}")


def is_destination(url, allow_relay=True):
    scp = re.fullmatch(r"git@github\.com:(.+)", url, re.IGNORECASE)
    if scp:
        return scp.group(1).lower().removesuffix(".git") == REPOSITORY
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        return False
    if parts.query or parts.fragment or not host:
        return False
    path = parts.path.strip("/").lower().removesuffix(".git")
    if host == "github.com":
        allowed = (parts.scheme == "https" and port in (None, 443)) or (
            parts.scheme == "ssh" and parts.username == "git" and port in (None, 22))
        return allowed and path == REPOSITORY
    if host == "ssh.github.com":
        return parts.scheme == "ssh" and parts.username == "git" and port == 443 and path == REPOSITORY
    # Only explicit GitHub repository paths on the checkout's local relay.
    if allow_relay and parts.scheme in ("http", "https") and host in ("localhost", "127.0.0.1", "::1"):
        return path in (REPOSITORY, f"github.com/{REPOSITORY}", f"github/{REPOSITORY}", f"git/{REPOSITORY}")
    return False


def publish(checkout, archive):
    archive = archive.resolve(strict=True)
    if not archive.is_file() or archive.suffix.lower() != ".zip":
        raise DeliveryError("Expected the finished ZIP file.")
    if any(ord(char) < 32 or ord(char) == 127 for char in archive.name) or "\\" in archive.name:
        raise DeliveryError("The archive name contains a control or path separator character.")
    if archive.stat().st_size > MAX_BYTES:
        raise DeliveryError("The archive exceeds the 100 MiB Git file limit.")
    path = "openvam/" + archive.name
    private_ref = "refs/openvam-publish/" + uuid.uuid4().hex

    with tempfile.TemporaryDirectory(prefix="openvam-publish-") as temporary:
        snapshot = Path(temporary) / "payload.zip"
        shutil.copyfile(archive, snapshot)
        size = snapshot.stat().st_size
        if size > MAX_BYTES:
            raise DeliveryError("The archive exceeds the 100 MiB Git file limit.")
        try:
            with zipfile.ZipFile(snapshot) as contents:
                if contents.testzip() is not None:
                    raise DeliveryError("A ZIP member failed CRC verification.")
        except (zipfile.BadZipFile, RuntimeError, EOFError, zlib.error) as exc:
            raise DeliveryError("The ZIP failed its integrity check.") from exc
        sha256 = hashlib.sha256()
        with snapshot.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                sha256.update(block)
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(temporary) / "index"),
                   GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never", GIT_LITERAL_PATHSPECS="1")

        def git(*args, input_data=None):
            proc = subprocess.run(["git", "-C", str(checkout), *args], input=input_data,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            if proc.returncode:
                operation = next((arg for arg in args if arg not in ("-c",) and "=" not in arg), args[0])
                raise GitError(operation, proc.stderr.decode("utf-8", "replace"))
            return proc.stdout

        configured = {"remote.origin.url": [], "remote.origin.pushurl": []}
        records = git("config", "-z", "--get-regexp", r"^remote\.origin\.(url|pushurl)$")
        for record in records.rstrip(b"\0").split(b"\0"):
            key, value = record.decode().split("\n", 1)
            configured[key].append(value)
        fetch_urls = configured["remote.origin.url"]
        push_urls = configured["remote.origin.pushurl"] or fetch_urls
        for flags, raw in (((), fetch_urls), (("--push",), push_urls)):
            actual = git("remote", "get-url", *flags, "--all", "origin").decode().splitlines()
            # A canonical repository URL may use the cloud's existing Git insteadOf transport.
            if len(raw) != 1 or len(actual) != 1 or not (
                    is_destination(actual[0]) or is_destination(raw[0], allow_relay=False)):
                raise DeliveryError(f"Expected origin to identify github.com/{REPOSITORY} for fetch and push.")
        # The isolated index and temporary ref leave the caller's HEAD, index and files intact.
        blob = git("hash-object", "-w", "--no-filters", "--", str(snapshot)).decode().strip()

        def remote_tip():
            git("fetch", "--quiet", "--no-tags", "--no-recurse-submodules", "--no-write-fetch-head",
                "--refmap=", "origin", f"+{BRANCH}:{private_ref}")
            return git("rev-parse", "--verify", private_ref).decode().strip()

        def entry(commit, name):
            data = git("ls-tree", "-z", commit, "--", name)
            if not data:
                return None
            mode, kind, oid = data.partition(b"\t")[0].decode("ascii").split()
            return mode, kind, oid

        def matches(commit):
            found = entry(commit, path)
            if found is None:
                return False
            if found[0] not in ("100644", "100755") or found[1:] != ("blob", blob):
                raise DeliveryError(f"An existing remote file has different content or type at {path}.")
            return True

        try:
            for attempt in range(ATTEMPTS):
                attempted_push = False
                try:
                    tip = remote_tip()
                    if matches(tip):
                        break
                    folder = entry(tip, "openvam")
                    if folder and folder[1] != "tree":
                        raise DeliveryError("The remote openvam path must be a directory.")
                    git("read-tree", tip)
                    git("update-index", "--add", "--cacheinfo", "100644", blob, path)
                    tree = git("write-tree").decode().strip()
                    commit = git("-c", "user.name=OpenVam Delivery", "-c",
                                 "user.email=openvam-delivery@users.noreply.github.com",
                                 "commit-tree", tree, "-p", tip,
                                 input_data=f"Deliver {archive.name}\n".encode()).decode().strip()
                    attempted_push = True
                    git("push", "--porcelain", "--no-follow-tags", "origin", f"{commit}:{BRANCH}")
                    tip = remote_tip()
                    if matches(tip):
                        break
                    raise GitError("verify", "the remote did not return the pushed path")
                except GitError:
                    if attempt == ATTEMPTS - 1:
                        # A dropped push response may follow a successful server-side update.
                        if attempted_push:
                            tip = remote_tip()
                            if matches(tip):
                                break
                        raise
                    time.sleep(2 ** attempt)
            return {
                "repository": REPOSITORY, "branch": "main", "path": path, "bytes": size,
                "sha256": sha256.hexdigest(), "verified_commit": tip, "git_blob": blob,
                "download_url": f"https://github.com/{REPOSITORY}/raw/{tip}/{quote(path)}",
            }
        finally:
            git("update-ref", "-d", private_ref)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip", type=Path, help="finished ZIP to deliver")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="deliveries checkout (default: current directory)")
    args = parser.parse_args()
    try:
        receipt = publish(args.repo, args.zip)
    except (DeliveryError, OSError, UnicodeError) as exc:
        parser.exit(1, f"Delivery failed: {exc}\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

