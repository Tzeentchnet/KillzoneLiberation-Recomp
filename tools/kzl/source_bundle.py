#!/usr/bin/env python3
"""Build a deterministic GPL corresponding-source zip.  -> T-8.3

The parent Git archive contains only the submodule gitlink, so this tool also
archives the exact `external/psp-recomp` commit pinned by the selected parent
revision. It refuses dirty/mismatched trees and runs the tracked-content audit
before producing the bundle.
"""

import argparse
import hashlib
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import content_audit  # noqa: E402


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
SUBMODULE_PATH = "external/psp-recomp"


class BundleError(RuntimeError):
    pass


def _git(repo, *args, text=True):
    result = subprocess.run(
        ["git", "-C", repo, *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
    )
    return result.stdout.strip() if text else result.stdout


def safe_version(value):
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    cleaned = cleaned.strip(".-")
    if not cleaned:
        raise BundleError("version is empty after sanitizing")
    return cleaned


def _pinned_submodule_commit(root, ref):
    line = _git(root, "ls-tree", ref, SUBMODULE_PATH)
    fields = line.split()
    if len(fields) < 3 or fields[1] != "commit":
        raise BundleError(f"{SUBMODULE_PATH} is not a gitlink in {ref}")
    return fields[2]


def _check_clean(root, submodule):
    parent_status = _git(
        root, "status", "--porcelain", "--untracked-files=normal",
        "--ignore-submodules=none",
    )
    child_status = _git(submodule, "status", "--porcelain", "--untracked-files=normal")
    if parent_status:
        raise BundleError("parent worktree is dirty")
    if child_status:
        raise BundleError("psp-recomp worktree is dirty")


def _extract_git_archive(repo, ref, destination):
    archive = _git(repo, "archive", "--format=tar", ref, text=False)
    destination_real = os.path.realpath(destination)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        for member in stream.getmembers():
            target = os.path.realpath(os.path.join(destination, member.name))
            if target != destination_real and not target.startswith(
                destination_real + os.sep
            ):
                raise BundleError(f"unsafe archive path: {member.name}")
        if hasattr(tarfile, "fully_trusted_filter"):
            stream.extractall(destination, filter="fully_trusted")
        else:
            stream.extractall(destination)


def _manifest(version, parent_commit, submodule_commit):
    return (
        "Killzone: Liberation Recomp corresponding source bundle\n"
        f"Version: {version}\n"
        f"Parent commit: {parent_commit}\n"
        f"external/psp-recomp commit: {submodule_commit}\n"
        "\n"
        "This archive contains the complete tracked source used by the project,\n"
        "including the exact runtime submodule tree. It intentionally contains no\n"
        "game disc, executable, generated game C/image, save data, or game assets.\n"
        "\n"
        "Combined license: GPL-2.0-or-later (LICENSE).\n"
        "Third-party terms and LGPL decoder source: CREDITS.md and\n"
        "external/psp-recomp/CREDITS.md.\n"
    )


def write_deterministic_zip(source_root, output):
    files = []
    for directory, _, names in os.walk(source_root):
        for name in names:
            path = os.path.join(directory, name)
            relative = os.path.relpath(path, os.path.dirname(source_root))
            files.append((relative.replace(os.sep, "/"), path))
    files.sort()

    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for relative, path in files:
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = stat.S_IMODE(os.stat(path).st_mode)
            info.external_attr = (stat.S_IFREG | mode) << 16
            with open(path, "rb") as stream:
                archive.writestr(info, stream.read())


def build_bundle(root, ref, version, output):
    root = os.path.abspath(root)
    submodule = os.path.join(root, *SUBMODULE_PATH.split("/"))
    _check_clean(root, submodule)
    parent_commit = _git(root, "rev-parse", f"{ref}^{{commit}}")
    checked_out_commit = _git(root, "rev-parse", "HEAD")
    if parent_commit != checked_out_commit:
        raise BundleError(
            f"selected ref is {parent_commit}, but checkout is {checked_out_commit}"
        )
    pinned_commit = _pinned_submodule_commit(root, ref)
    actual_commit = _git(submodule, "rev-parse", "HEAD")
    if actual_commit != pinned_commit:
        raise BundleError(
            f"submodule mismatch: parent pins {pinned_commit}, checkout is {actual_commit}"
        )

    audited, findings = content_audit.audit_repository(root)
    if findings:
        details = "; ".join(
            f"{path}: {', '.join(issues)}" for path, issues in findings
        )
        raise BundleError(f"content audit rejected source tree: {details}")

    top_name = f"KillzoneLiberation-Recomp-{safe_version(version)}-source"
    with tempfile.TemporaryDirectory(prefix="kzl-source-bundle-") as temporary:
        top = os.path.join(temporary, top_name)
        os.makedirs(top)
        _extract_git_archive(root, ref, top)
        submodule_destination = os.path.join(
            top, *SUBMODULE_PATH.split("/")
        )
        if os.path.exists(submodule_destination):
            if os.path.isdir(submodule_destination):
                shutil.rmtree(submodule_destination)
            else:
                os.remove(submodule_destination)
        os.makedirs(submodule_destination)
        _extract_git_archive(submodule, pinned_commit, submodule_destination)
        with open(
            os.path.join(top, "SOURCE-BUNDLE-MANIFEST.txt"),
            "w", encoding="ascii", newline="\n",
        ) as stream:
            stream.write(
                _manifest(version, parent_commit, pinned_commit)
            )
        write_deterministic_zip(top, output)

    digest = hashlib.sha256()
    with open(output, "rb") as stream:
        while True:
            block = stream.read(1 << 20)
            if not block:
                break
            digest.update(block)
    return {
        "output": os.path.abspath(output),
        "sha256": digest.hexdigest(),
        "bytes": os.path.getsize(output),
        "files_audited": audited,
        "parent_commit": parent_commit,
        "submodule_commit": pinned_commit,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=ROOT)
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--version")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        version = args.version or _git(args.root, "describe", "--tags", "--always")
        version = safe_version(version)
        output = args.output or os.path.join(
            args.root, "dist",
            f"KillzoneLiberation-Recomp-{version}-source.zip",
        )
        result = build_bundle(args.root, args.ref, version, output)
    except (
        BundleError, OSError, subprocess.CalledProcessError,
        KeyError, tarfile.TarError,
    ) as exc:
        print(f"source_bundle: {exc}", file=sys.stderr)
        return 1
    print(
        f"source bundle: {result['output']} ({result['bytes']:,} bytes)\n"
        f"SHA-256: {result['sha256']}\n"
        f"parent: {result['parent_commit']}\n"
        f"psp-recomp: {result['submodule_commit']}\n"
        f"audited files: {result['files_audited']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
