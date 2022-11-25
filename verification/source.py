"""Bind evidence to committed Git blobs and the separately trusted checkout.

Legacy inventories retain their exact file-selection policy. Product inventories
also cover browser assets, native headers and executable JavaScript tests.
"""

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

LEGACY = "caissa-source-v1"
PRODUCT = "caissa-source-v2"
MAX_FILES = 10000
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
FIXED = {
    "CMakeLists.txt",
    "Makefile",
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    "docs/EXPERIMENT_PLAN.md",
}
LEGACY_SUFFIXES = {
    ".cpp",
    ".hpp",
    ".py",
    ".ts",
    ".toml",
    ".lock",
    ".yml",
    ".yaml",
    ".cai",
}
PRODUCT_SUFFIXES = LEGACY_SUFFIXES | {
    ".h",
    ".hxx",
    ".cc",
    ".cxx",
    ".cmake",
    ".js",
    ".mjs",
    ".html",
    ".css",
}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def relative_path(name):
    require(
        isinstance(name, str) and 0 < len(name.encode("utf8")) <= 4096,
        "source path has invalid type or length",
    )
    require(
        not name.startswith("/")
        and "\\" not in name
        and all(part not in {"", ".", ".."} for part in name.split("/"))
        and all(ord(c) >= 32 and ord(c) != 127 for c in name),
        "source path is not a safe canonical relative name",
    )
    return name


def selected(name, policy):
    require(policy in {LEGACY, PRODUCT}, "unsupported source inventory policy")
    suffixes = LEGACY_SUFFIXES if policy == LEGACY else PRODUCT_SUFFIXES
    return not name.startswith(("results/", "docs/images/")) and (
        Path(name).suffix in suffixes or name in FIXED or name.startswith("config/")
    )


@dataclass(frozen=True)
class Blob:
    name: str
    identity: str
    size: int


def inventory(checkout, commit, policy=LEGACY):
    require(
        isinstance(commit, str) and re.fullmatch("[0-9a-f]{40}", commit),
        "trusted source commit is malformed",
    )
    result = subprocess.run(
        ["git", "ls-tree", "-r", "-l", "-z", "--full-tree", commit],
        cwd=checkout,
        capture_output=True,
        timeout=10,
        check=True,
    )
    require(
        len(result.stdout) <= 2 * 1024 * 1024,
        "trusted source tree exceeds inventory ceiling",
    )
    blobs = []
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        name = relative_path(raw_name.decode("utf8"))
        if not selected(name, policy):
            continue
        fields = metadata.split()
        require(
            len(fields) == 4
            and fields[0] in {b"100644", b"100755"}
            and fields[1] == b"blob"
            and re.fullmatch(b"[0-9a-f]{40}", fields[2]),
            "trusted source contains a link, submodule or unsupported object",
        )
        size = int(fields[3])
        require(0 <= size <= MAX_FILE_BYTES, "trusted source blob exceeds byte ceiling")
        blobs.append(Blob(name, fields[2].decode("ascii"), size))
    require(
        0 < len(blobs) <= MAX_FILES and len({b.name for b in blobs}) == len(blobs),
        "trusted source inventory is empty, duplicated or excessive",
    )
    require(
        sum(b.size for b in blobs) <= MAX_TOTAL_BYTES,
        "trusted source aggregate byte ceiling exceeded",
    )
    return sorted(blobs, key=lambda b: b.name)


def snapshot(checkout, commit, policy=LEGACY):
    blobs = inventory(checkout, commit, policy)
    query = "".join(blob.identity + "\n" for blob in blobs).encode("ascii")
    result = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=checkout,
        input=query,
        capture_output=True,
        timeout=15,
        check=True,
    )
    require(
        len(result.stdout) <= MAX_TOTAL_BYTES + MAX_FILES * 128,
        "trusted source blob response exceeds bounded inventory",
    )
    cursor = 0
    identities = {}
    for blob in blobs:
        end = result.stdout.find(b"\n", cursor)
        require(end >= cursor, "truncated trusted source blob header")
        fields = result.stdout[cursor:end].split()
        require(
            fields
            == [blob.identity.encode("ascii"), b"blob", str(blob.size).encode("ascii")],
            "trusted source blob identity, type or length differs",
        )
        begin = end + 1
        end = begin + blob.size
        require(
            result.stdout[end : end + 1] == b"\n",
            "truncated trusted source blob payload",
        )
        identities[blob.name] = hashlib.sha256(result.stdout[begin:end]).hexdigest()
        cursor = end + 1
    require(cursor == len(result.stdout), "unexpected trailing source blob response")
    return identities


def verify_checkout(checkout, manifest, expected_commit, policy=LEGACY):
    checkout = Path(checkout).resolve()
    require(isinstance(manifest, dict), "source manifest must be an object")
    require(
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=checkout, text=True, timeout=5
        ).strip()
        == expected_commit,
        "trusted checkout is not the expected executable source commit",
    )
    require(manifest.get("commit") == expected_commit, "source commit mismatch")
    if policy == PRODUCT:
        require(
            manifest.get("schema") == "caissa-source-inputs-v2"
            and manifest.get("policy") == PRODUCT,
            "full source inventory must include product assets",
        )
    expected = snapshot(checkout, expected_commit, policy)
    require(
        manifest.get("files") == expected,
        "source inventory or hashes differ from trusted Git blobs",
    )
    # Hashes in a bundle cannot bless uncommitted edits at an unchanged HEAD.
    for name, digest in expected.items():
        path = checkout
        for part in name.split("/"):
            path = path / part
            require(
                not path.is_symlink(),
                "trusted checkout source traverses a symbolic link",
            )
        require(
            path.is_file() and path.stat().st_size <= MAX_FILE_BYTES,
            "trusted checkout source is missing or excessive",
        )
        require(
            hashlib.sha256(path.read_bytes()).hexdigest() == digest,
            "trusted checkout bytes differ from the expected commit: " + name,
        )
    return expected


def main():
    import argparse
    import json
    from verification.bundle import strict_json

    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--policy", choices=[LEGACY, PRODUCT], default=PRODUCT)
    args = parser.parse_args()
    try:
        require(
            args.manifest.is_file()
            and not args.manifest.is_symlink()
            and args.manifest.stat().st_size <= 4 * 1024 * 1024,
            "source manifest is unsafe or excessive",
        )
        identities = verify_checkout(
            args.checkout,
            strict_json(args.manifest.read_bytes()),
            args.expected_commit,
            args.policy,
        )
        print(
            json.dumps(
                {
                    "status": "passed",
                    "source_commit": args.expected_commit,
                    "source_files": len(identities),
                    "policy": args.policy,
                    "full_acceptance": False,
                }
            )
        )
        return 0
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        print(
            json.dumps(
                {"status": "rejected", "reason": str(error), "full_acceptance": False}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
