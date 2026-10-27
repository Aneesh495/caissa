"""Create one immutable evidence-data branch after the existing timed owners exit.

Uploads existing gzip bytes through GitHub blobs. It never packs, decodes gzip,
changes a game, publishes a release, force-updates a ref or rewrites main.
"""

import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

from tools.host_lease import HostLease

REPOSITORY = "Aneesh495/caissa"
INDEX_SHA = "493405d717001b10e5406287b6f42138cd73de61677794d96183b73e9cfaaa40"
RAW_SHA = "46b7378b5432b26733d12427d4cde1960f6f0e495814e93e41be4868c44f204e"
PARENT = 1793150297.974828
BRANCH = "evidence-g02-volumes-v1"


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def regular_bytes(path, expected_bytes, expected_sha):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(before.st_mode)
            and 0 < before.st_size == expected_bytes <= 8 * 1024**2,
            "hosting member size or type differs",
        )
        data = stream.read(expected_bytes + 1)
        after = os.fstat(stream.fileno())
        require(
            (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ),
            "hosting member changed during read",
        )
    require(
        len(data) == expected_bytes and digest(data) == expected_sha,
        "hosting member byte identity differs",
    )
    return data


def admit(plan):
    require(
        len(plan["frozen_source_files"]) == 4, "hosting frozen source inventory differs"
    )
    require(
        plan["wait_deadline_unix"] <= plan["wait_origin_unix"] + 43200
        and plan["wait_deadline_unix"] <= PARENT - 7200,
        "hosting wait ceiling differs",
    )
    require(
        plan["repository"] == REPOSITORY and plan["branch"] == BRANCH,
        "hosting repository or create-only branch differs",
    )
    require(
        plan["parent_deadline_unix"] == PARENT
        and plan["maximum_upload_seconds"] == 7200,
        "hosting parent or upload ceiling differs",
    )
    require(
        plan["maximum_upload_attempts"] == 2
        and plan["minimum_write_interval_seconds"] == 8,
        "hosting attempt or API pacing differs",
    )
    require(
        re.fullmatch("[a-f0-9]{40}", plan["base_commit"]),
        "hosting base source is invalid",
    )
    require(
        plan["index_sha256"] == INDEX_SHA and plan["original_sha256"] == RAW_SHA,
        "hosting original byte pins differ",
    )
    require(
        plan["original_bytes"] == 5349131147
        and plan["gzip_bytes"] == 507807163
        and plan["volume_count"] == 319,
        "hosting original schedule differs",
    )
    require(not Path(plan["packet_root"]).is_symlink(), "hosting packet root is linked")
    root = Path(plan["packet_root"]).resolve(strict=True)
    require(not (root / "volumes").is_symlink(), "hosting volume directory is linked")
    raw = regular_bytes(root / "VOLUMES.json", 74233, INDEX_SHA)
    index = json.loads(raw)
    require(
        index["schema"] == "caissa-portable-evidence-volumes-v1"
        and index["semantic_verification_required"] is True,
        "hosting index schema or semantic promotion differs",
    )
    require(
        index["raw_sha256"] == RAW_SHA
        and index["raw_bytes"] == 5349131147
        and len(index["volumes"]) == 319,
        "hosting index original differs",
    )
    require(
        sum(row["gzip_bytes"] for row in index["volumes"]) == 507807163,
        "hosting gzip byte sum differs",
    )
    for number, row in enumerate(index["volumes"]):
        require(
            row["path"] == f"volumes/{number:06d}.gz"
            and 0 < row["gzip_bytes"] <= 8 * 1024**2,
            "hosting volume path or byte ceiling differs",
        )
        require(
            re.fullmatch("[a-f0-9]{64}", row["gzip_sha256"]),
            "hosting volume identity is invalid",
        )
        path = root / row["path"]
        require(
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size == row["gzip_bytes"],
            "hosting volume metadata differs",
        )
    return root, raw, index


class GitHub:
    def __init__(self, tick, interval=8, error_path=None):
        self.tick, self.interval, self.last_write = tick, interval, 0
        self.error_path = error_path

    def error(self, operation, error):
        if self.error_path is not None:
            require(
                not self.error_path.exists()
                or self.error_path.stat().st_size < 1024**2,
                "hosting HTTP error log ceiling exhausted",
            )
            with self.error_path.open("a") as stream:
                stream.write(
                    json.dumps(
                        {
                            "operation": operation,
                            "error_type": type(error).__name__,
                            "observed_unix": time.time(),
                        }
                    )
                    + "\n"
                )

    def request(self, method, path, value=None, *, absent=False):
        self.tick()
        if method != "GET":
            while time.monotonic() - self.last_write < self.interval:
                self.tick()
                time.sleep(min(1, self.interval - (time.monotonic() - self.last_write)))
            self.last_write = time.monotonic()
        environment = {
            key: value
            for key, value in os.environ.items()
            if key not in {"GH_DEBUG", "GIT_TRACE", "GIT_CURL_VERBOSE"}
        }
        command = ["gh", "api", "--method", method, f"repos/{REPOSITORY}/{path}"]
        if value is not None:
            command += ["--input", "-"]
        remaining = self.tick()
        timeout = 30 if remaining is None else min(30, remaining)
        require(timeout > 0, "hosting request deadline exhausted")
        actual = subprocess.run(
            command,
            input=json.dumps(value) if value is not None else None,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=environment,
        )
        if actual.returncode:
            if absent and "HTTP 404" in actual.stderr:
                return None
            # Authentication values are never copied from environment or debug output.
            status = re.search(r"HTTP (\d{3})", actual.stderr)
            raise ValueError(
                "GitHub evidence request failed: "
                + (status.group(0) if status else "CLI failure")
            )
        return json.loads(actual.stdout)


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def dependencies_closed(plan):
    require(time.time() < PARENT, "original parent deadline exhausted")
    rows = []
    for item in plan["timed_dependencies"]:
        try:
            closed = (
                json.loads(Path(item["active_usage"]).read_text())["closed"] is True
            )
        except (OSError, ValueError, KeyError):
            closed = False
        rows.append(
            {
                "name": item["name"],
                "ledger_closed": closed,
                "expected_owner_alive": alive(item["pid"]),
            }
        )
    return (
        all(row["ledger_closed"] and not row["expected_owner_alive"] for row in rows),
        rows,
    )


def publish(plan, work, lease):
    root, index_raw, index = admit(plan)
    scope_path = work / "HOSTING_SCOPE.json"
    if scope_path.exists():
        scope = json.loads(scope_path.read_text())
        require(
            scope["plan_sha256"] == digest(json.dumps(plan, sort_keys=True).encode()),
            "hosting resume plan changed",
        )
    else:
        now = time.time()
        scope = {
            "origin_unix": now,
            "deadline_unix": min(now + 7200, PARENT),
            "attempts_started": 0,
            "plan_sha256": digest(json.dumps(plan, sort_keys=True).encode()),
            "full_G15_certified": False,
        }
    require(scope["attempts_started"] < 2, "hosting upload attempts exhausted")
    scope["attempts_started"] += 1
    scope["pid"] = os.getpid()
    atomic(scope_path, scope)
    atomic(
        work / "QUEUE_PROGRESS.json",
        {
            "status": "timed-dependencies-exited-hosting-lease-acquired",
            "pid": os.getpid(),
            "observed_unix": time.time(),
        },
    )

    def tick():
        lease.check()
        require(
            time.time() < scope["deadline_unix"],
            "hosting fixed wall deadline exhausted",
        )
        require(
            shutil.disk_usage(work).free >= 10 * 1024**3,
            "hosting free-space reserve exhausted",
        )
        require(
            sum(p.stat().st_size for p in work.rglob("*") if p.is_file()) <= 1024**3,
            "hosting additional evidence ceiling exhausted",
        )
        return scope["deadline_unix"] - time.time()

    api = GitHub(tick, error_path=work / "HTTP_ERRORS.jsonl")
    refs = "git/ref/heads/" + BRANCH
    existing = api.request("GET", refs, absent=True)
    own_commit = (
        json.loads((work / "COMMIT.json").read_text())
        if (work / "COMMIT.json").exists()
        else None
    )
    require(
        existing is None
        or (own_commit and existing["object"]["sha"] == own_commit["sha"]),
        "create-only evidence branch already exists",
    )
    blobs_path = work / "BLOBS.json"
    blobs = json.loads(blobs_path.read_text()) if blobs_path.exists() else {}

    def upload(name, data):
        git_sha = hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest()
        if name in blobs:
            require(
                blobs[name]["sha"] == git_sha and blobs[name]["sha256"] == digest(data),
                "hosting resume blob receipt differs",
            )
            return git_sha
        last = None
        for _ in range(3):
            try:
                actual = api.request(
                    "POST",
                    "git/blobs",
                    {"encoding": "base64", "content": base64.b64encode(data).decode()},
                )
                require(actual["sha"] == git_sha, "GitHub stored blob identity differs")
                blobs[name] = {
                    "sha": git_sha,
                    "sha256": digest(data),
                    "bytes": len(data),
                }
                atomic(blobs_path, blobs)
                return git_sha
            except (subprocess.TimeoutExpired, ValueError) as error:
                api.error("upload-original-blob", error)
                last = error
                tick()
        raise last

    entries = []
    for row in [
        {
            "path": "VOLUMES.json",
            "gzip_bytes": len(index_raw),
            "gzip_sha256": INDEX_SHA,
        },
        *index["volumes"],
    ]:
        tick()
        data = (
            index_raw
            if row["path"] == "VOLUMES.json"
            else regular_bytes(
                root / row["path"], row["gzip_bytes"], row["gzip_sha256"]
            )
        )
        entries.append(
            {
                "path": row["path"],
                "mode": "100644",
                "type": "blob",
                "sha": upload(row["path"], data),
            }
        )
        atomic(
            work / "HOSTING_PROGRESS.json",
            {
                "phase": "uploading-original-byte-members",
                "complete_members": len(entries),
                "total_members": 320,
                "uploaded_bytes": sum(item["bytes"] for item in blobs.values()),
                "pid": os.getpid(),
                "observed_unix": time.time(),
            },
        )
    if own_commit is None:
        tree = api.request("POST", "git/trees", {"tree": entries})
        commit = api.request(
            "POST",
            "git/commits",
            {
                "message": "Publish frozen original G02 evidence volume bodies [skip ci]",
                "tree": tree["sha"],
                "parents": [plan["base_commit"]],
            },
        )
        own_commit = {
            "sha": commit["sha"],
            "tree_sha": tree["sha"],
            "base_commit": plan["base_commit"],
            "branch": BRANCH,
        }
        atomic(work / "COMMIT.json", own_commit)
    if existing is None:
        api.request(
            "POST",
            "git/refs",
            {"ref": "refs/heads/" + BRANCH, "sha": own_commit["sha"]},
        )
    require(
        api.request("GET", refs)["object"]["sha"] == own_commit["sha"],
        "published evidence ref differs",
    )
    verified = []
    for row in [
        {
            "path": "VOLUMES.json",
            "gzip_bytes": len(index_raw),
            "gzip_sha256": INDEX_SHA,
        },
        *index["volumes"],
    ]:
        tick()
        url = f"https://raw.githubusercontent.com/{REPOSITORY}/{own_commit['sha']}/{row['path']}"
        raw = None
        for _ in range(3):
            try:
                remaining = min(30, tick())
                response = subprocess.run(
                    [
                        "curl",
                        "-fsSL",
                        "--max-time",
                        str(remaining),
                        "--max-filesize",
                        str(row["gzip_bytes"] + 1),
                        url,
                    ],
                    capture_output=True,
                    timeout=remaining,
                )
                require(
                    response.returncode == 0, "public evidence HTTP retrieval failed"
                )
                raw = response.stdout
                break
            except (ValueError, subprocess.TimeoutExpired) as error:
                api.error("retrieve-public-original-member", error)
                tick()
                time.sleep(1)
        require(
            raw is not None
            and len(raw) == row["gzip_bytes"]
            and digest(raw) == row["gzip_sha256"],
            "public evidence download differs",
        )
        verified.append({"path": row["path"], "sha256": digest(raw), "bytes": len(raw)})
        atomic(
            work / "DOWNLOAD_PROGRESS.json",
            {
                "phase": "verifying-public-downloads",
                "complete_members": len(verified),
                "total_members": 320,
                "observed_unix": time.time(),
            },
        )
    result = {
        "status": "passed original-byte hosting and public retrieval",
        "commit": own_commit,
        "members": verified,
        "original_bytes": 5349131147,
        "original_sha256": RAW_SHA,
        "index_sha256": INDEX_SHA,
        "new_compression_or_gzip_decode": False,
        "semantic_verification_repeated": False,
        "release_published": False,
        "full_G15_certified": False,
        "full_acceptance": False,
        "closed_unix": time.time(),
    }
    atomic(work / "RESULT.json", result)
    scope["closed"] = True
    atomic(scope_path, scope)
    return result


def run(plan, work, check_only=False):
    require(
        not (work / "RESULT.json").exists(),
        "hosting result is already closed; no status rerun",
    )
    admit(plan)
    for name, value in plan["frozen_source_files"].items():
        require(
            digest(Path(name).read_bytes()) == value,
            "frozen hosting implementation changed",
        )
    if check_only:
        api = GitHub(
            lambda: require(
                time.time() < plan["wait_deadline_unix"],
                "hosting admission deadline exhausted",
            )
        )
        require(
            api.request("GET", "git/ref/heads/" + BRANCH, absent=True) is None,
            "hosting create-only branch already exists",
        )
        require(
            api.request("GET", "git/commits/" + plan["base_commit"])["sha"]
            == plan["base_commit"],
            "hosting parent source is unavailable",
        )
        closed, rows = dependencies_closed(plan)
        return {
            "status": "metadata and authenticated create-only admission passed",
            "heavy_dependencies_closed": closed,
            "dependencies": rows,
            "body_hashing_upload_or_scope_started": False,
            "full_G15_certified": False,
        }
    lock = (work / "QUEUE_OWNER.lock").open("a")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    lease = None
    try:
        if (work / "HOSTING_SCOPE.json").exists():
            # A previously admitted upload keeps its own original deadline. It
            # does not receive another queue window or wait behind new work.
            closed, _rows = dependencies_closed(plan)
            require(closed, "hosting resume requires exited timed dependencies")
            lease = HostLease(Path(plan["project"]) / "runs")
            return publish(plan, work, lease)
        while True:
            require(
                time.time() < plan["wait_deadline_unix"],
                "hosting finite queue deadline exhausted",
            )
            for name, value in plan["frozen_source_files"].items():
                require(
                    digest(Path(name).read_bytes()) == value,
                    "frozen hosting implementation changed while queued",
                )
            closed, rows = dependencies_closed(plan)
            if closed:
                try:
                    lease = HostLease(Path(plan["project"]) / "runs")
                    break
                except ValueError:
                    pass
            atomic(
                work / "QUEUE_PROGRESS.json",
                {
                    "status": "waiting-for-existing-timed-owners",
                    "dependencies": rows,
                    "pid": os.getpid(),
                    "observed_unix": time.time(),
                },
            )
            time.sleep(5)
        return publish(plan, work, lease)
    except BaseException as error:
        atomic(
            work / ("FAILED-" + str(time.time_ns()) + ".json"),
            {
                "reason": str(error),
                "observed_unix": time.time(),
                "scope_preserved": True,
            },
        )
        raise
    finally:
        if lease is not None:
            lease.close()
        lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    raw = args.plan.read_bytes()
    require(
        digest(raw) == args.expected_plan_sha256,
        "external hosting plan identity differs",
    )
    print(json.dumps(run(json.loads(raw), args.plan.parent, args.check_only)))


if __name__ == "__main__":
    main()
