#!/usr/bin/env python3
"""Reject tracked game/generated payloads before source distribution.  -> T-8.2

Audits both this repository and the pinned psp-recomp submodule. In addition to
path/extension and binary-magic checks, every tracked file is compared with the
known game-file SHA-1 values in config/kzl.toml so renamed payloads are caught.
The two PPSSPP free replacement PGF files are pinned by SHA-256.
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tomllib


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

PROHIBITED_SUFFIXES = {".iso", ".cso", ".prx", ".pbp", ".elf"}
PROHIBITED_NAMES = {
    "boot.bin",
    "chapter5.bin",
    "eboot.bin",
    "kzl.bin",
    "psp.dat",
    "umd_data.bin",
}
GENERATED_C = re.compile(
    r"(?:^|/)kzl_recomp(?:_[0-9]{3}|_register)?\.c$", re.IGNORECASE
)
ALLOWED_DAT_PREFIX = "external/psp-recomp/assets/vfpu/"
ALLOWED_DLL = "external/psp-recomp/SDL3.dll"
FONT_HASHES = {
    "external/psp-recomp/font/jpn0.pgf":
        "d363cec75fecfafd1511e370e48c748c30199c694b83a4026be34d799b192917",
    "external/psp-recomp/font/ltn0.pgf":
        "1184f16bc89bad1fea49093806784470281af54f279b57ef0378ce33e6603870",
}


def _git_files(repo):
    result = subprocess.run(
        [
            "git", "-C", repo, "ls-files", "-z",
            "--cached", "--others", "--exclude-standard",
        ],
        check=True,
        stdout=subprocess.PIPE,
    )
    return [
        item.decode("utf-8", "surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    ]


def _sha1(path):
    digest = hashlib.sha1()
    with open(path, "rb") as stream:
        while True:
            block = stream.read(1 << 20)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _known_game_hashes(root):
    with open(os.path.join(root, "config", "kzl.toml"), "rb") as stream:
        config = tomllib.load(stream)
    hashes = {config["disc"]["iso_sha1"].lower()}
    hashes.update(value.lower() for value in config["disc"]["files"].values())
    return hashes


def audit_file(display_path, path, forbidden_hashes):
    normalized = display_path.replace("\\", "/")
    lower = normalized.lower()
    basename = os.path.basename(lower)
    suffix = os.path.splitext(lower)[1]
    issues = []

    if lower.startswith(("build/", "out/", "gen/")):
        issues.append("tracked build/generated output")
    if suffix in PROHIBITED_SUFFIXES:
        issues.append(f"prohibited game-container extension {suffix}")
    if suffix == ".dat" and not lower.startswith(ALLOWED_DAT_PREFIX):
        issues.append("tracked DAT payload outside the VFPU-table allowlist")
    if suffix == ".dll" and lower != ALLOWED_DLL.lower():
        issues.append("unexpected tracked DLL")
    if basename in PROHIBITED_NAMES:
        issues.append(f"prohibited game payload name {basename}")
    if basename == "kzl_image.bin" or GENERATED_C.search(lower):
        issues.append("generated game code/image")

    with open(path, "rb") as stream:
        header = stream.read(0x8006)
    if header.startswith(b"\x7fELF"):
        issues.append("ELF/PRX executable signature")
    if header.startswith(b"~PSP"):
        issues.append("encrypted PSP executable signature")
    if header.startswith(b"PSMF"):
        issues.append("PSMF movie signature")
    if len(header) >= 0x8006 and header[0x8001:0x8006] == b"CD001":
        issues.append("ISO9660 disc-image signature")

    digest = _sha1(path)
    if digest in forbidden_hashes:
        issues.append(f"matches known game payload SHA-1 {digest}")

    if suffix == ".pgf":
        expected = FONT_HASHES.get(lower)
        with open(path, "rb") as stream:
            actual = hashlib.sha256(stream.read()).hexdigest()
        if expected is None:
            issues.append("unapproved tracked PGF font")
        elif actual != expected:
            issues.append(
                f"replacement font hash changed: {actual}, expected {expected}"
            )
    return issues


def audit_repository(root):
    repositories = [
        (root, ""),
        (
            os.path.join(root, "external", "psp-recomp"),
            "external/psp-recomp/",
        ),
    ]
    forbidden_hashes = _known_game_hashes(root)
    findings = []
    audited = 0
    for repo, prefix in repositories:
        if not os.path.isdir(os.path.join(repo, ".git")) and not os.path.isfile(
            os.path.join(repo, ".git")
        ):
            findings.append((prefix.rstrip("/"), ["submodule is not initialized"]))
            continue
        for relative in _git_files(repo):
            if not prefix and relative.replace("\\", "/") == "external/psp-recomp":
                continue
            path = os.path.join(repo, relative)
            if not os.path.isfile(path):
                continue
            display = prefix + relative.replace("\\", "/")
            issues = audit_file(display, path, forbidden_hashes)
            audited += 1
            if issues:
                findings.append((display, issues))
    return audited, findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=ROOT)
    args = parser.parse_args(argv)
    root = os.path.abspath(args.root)
    try:
        audited, findings = audit_repository(root)
    except (OSError, subprocess.CalledProcessError, KeyError) as exc:
        print(f"content_audit: {exc}", file=sys.stderr)
        return 2
    if findings:
        for path, issues in findings:
            for issue in issues:
                print(f"ERROR: {path}: {issue}", file=sys.stderr)
        print(
            f"content audit failed: {len(findings)} tracked file(s) rejected",
            file=sys.stderr,
        )
        return 1
    print(
        f"content audit passed: {audited} tracked files; "
        f"{len(FONT_HASHES)} pinned free replacement fonts"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
