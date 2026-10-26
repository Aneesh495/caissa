"""Download only prospectively pinned immutable recovery archives.

This prepares audit inputs. It invokes no recovery producer or native program.
The independent reader verifies the original ZIP bytes and selects raw positives.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from tools.host_lease import ENVIRONMENT, inherited
from verification.source import PRODUCT, snapshot

PROFILE = "b2c23e734029d13800a27e4f237b2855fdbdf718c11cecec30cbc42154a3f627"


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            digest.update(block)
    return digest.hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


def download(descriptor, target, tick):
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise ValueError("G11 archive input preparation requires a scoped GitHub token")
    request = urllib.request.Request(
        "https://api.github.com/repos/Aneesh495/caissa/actions/artifacts/"
        + str(descriptor["artifact_id"])
        + "/zip",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "Caissa-immutable-recovery-audit",
        },
    )
    try:
        response = urllib.request.build_opener(NoRedirect).open(request, timeout=10)
    except urllib.error.HTTPError as error:
        if error.code != 302:
            raise ValueError(
                "G11 pinned artifact request failed with HTTP " + str(error.code)
            ) from None
        location = error.headers.get("Location", "")
        if not location.startswith("https://"):
            raise ValueError("G11 artifact redirect is not HTTPS")
        # The GitHub credential never follows the redirect to artifact storage.
        try:
            response = urllib.request.urlopen(
                urllib.request.Request(
                    location, headers={"User-Agent": "Caissa-immutable-recovery-audit"}
                ),
                timeout=10,
            )
        except urllib.error.URLError:
            raise ValueError(
                "G11 original artifact storage request failed; signed redirect omitted"
            ) from None
    target.parent.mkdir(parents=True, exist_ok=True)
    digest, count = hashlib.sha256(), 0
    with response, target.open("xb") as stream:
        while block := response.read(1048576):
            tick()
            count += len(block)
            if count > descriptor["archive_bytes"]:
                raise ValueError(
                    "G11 pinned artifact download exceeded its fixed length"
                )
            digest.update(block)
            stream.write(block)
    if (
        count != descriptor["archive_bytes"]
        or digest.hexdigest() != descriptor["archive_sha256"]
    ):
        raise ValueError("G11 downloaded original ZIP identity differs")
    return {
        "path": str(target),
        "bytes": count,
        "sha256": digest.hexdigest(),
        "artifact_id": descriptor["artifact_id"],
    }


def prepare(output):
    project = Path(__file__).resolve().parents[1]
    output = Path(output).resolve()
    if not inherited(project / "runs/TIMED_STRENGTH.lock"):
        raise ValueError(
            "G11 archive preparation requires the real inherited host lease"
        )
    profile = project / "config/recovery-join-v1.json"
    if output.exists() or sha(profile) != PROFILE:
        raise ValueError("G11 immutable audit output or prospective profile differs")
    rule = json.loads(profile.read_text())
    artifacts = project / "config/recovery-join-artifacts-v1.json"
    if sha(artifacts) != rule["artifacts_sha256"]:
        raise ValueError("G11 original artifact pins changed")
    origins = json.loads(artifacts.read_text())
    platform = "macos" if sys.platform == "darwin" else "linux"
    output.mkdir(parents=True)
    start, wall = time.monotonic(), time.time()
    downloads = {}

    def tick():
        if (
            time.monotonic() - start >= 180
            or time.time() >= wall + 180
            or not inherited(project / "runs/TIMED_STRENGTH.lock")
        ):
            raise ValueError(
                "G11 original input download time or ownership ceiling exhausted"
            )
        if shutil.disk_usage(output).free < 10 * 1024**3:
            raise ValueError("G11 input download free-space reserve exhausted")

    for role in ["arena", "training", "data"]:
        descriptor = origins[role]["platforms"][platform]
        downloads[role] = download(
            descriptor, output / "archives" / (role + ".zip"), tick
        )
        write(output / "DOWNLOADS.json", downloads)
    for origin, name in [
        (profile, "PROFILE.json"),
        (artifacts, "ARTIFACTS.json"),
        (project / "results/saved-v4-runtime-inputs/caissa", "engine"),
        (project / "results/precision-v4-2026-10-25/selected-v4.cai", "network.cai"),
        (project / "config/protocol-v4.json", "V4.json"),
        (
            project / "results/full-model-v3-2026-10-25/MODEL_CAMPAIGN.json",
            "MODEL_CAMPAIGN.json",
        ),
    ]:
        shutil.copy2(origin, output / name)
    source = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=project, text=True, timeout=5
    ).strip()
    write(
        output / "SOURCE_INPUTS.json",
        {
            "schema": "caissa-source-inputs-v2",
            "policy": PRODUCT,
            "commit": source,
            "files": snapshot(project, source, PRODUCT),
        },
    )
    write(
        output / "CONFIG.json",
        {
            "schema": "caissa-recovery-join-inputs-v1",
            "source_commit": source,
            "platform": platform,
            "profile_sha256": PROFILE,
            "engine_sha256": sha(output / "engine"),
            "network_sha256": sha(output / "network.cai"),
            "archives": {
                role: {"path": "archives/" + role + ".zip", "sha256": record["sha256"]}
                for role, record in downloads.items()
            },
            "maximum_download_seconds": 180,
            "started_unix": wall,
            "deadline_unix": wall + 180,
            "full_acceptance": False,
        },
    )
    tick()
    write(
        output / "MANIFEST.json",
        {
            "files": {
                str(p.relative_to(output)): sha(p)
                for p in sorted(output.rglob("*"))
                if p.is_file()
            }
        },
    )
    return {
        "source_commit": source,
        "manifest_sha256": sha(output / "MANIFEST.json"),
        "archives": downloads,
        "elapsed_seconds": time.monotonic() - start,
        "recovery_producers_executed": False,
        "full_acceptance": False,
    }
