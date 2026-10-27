"""Storage admission controls use real hardlinks and sparse files."""

from pathlib import Path
import tempfile

from tools.storage_budget import MAC_LIMIT, PROJECT_LIMIT, admission, footprint


def rejects(*values):
    try:
        admission(*values)
    except ValueError:
        return
    raise AssertionError("storage overflow was admitted")


def run():
    admission(PROJECT_LIMIT, MAC_LIMIT)
    admission(PROJECT_LIMIT - 30, MAC_LIMIT - 30, 20, 10)
    cases = 2
    for values in (
        (PROJECT_LIMIT + 1, 0),
        (0, MAC_LIMIT + 1),
        (PROJECT_LIMIT - 1, 0, 2),
        (0, MAC_LIMIT - 1, 2),
        (PROJECT_LIMIT - 20, 0, 10, 11),
        (0, MAC_LIMIT - 20, 10, 11),
        (-1, 0),
        (0, 0, -1),
        (True, 0),
    ):
        rejects(*values)
        cases += 1
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        original = root / "original"
        original.write_bytes(b"x" * 4096)
        linked = root / "linked"
        linked.hardlink_to(original)
        single = footprint([original])
        both = footprint([original, linked])
        assert both == single
        cases += 1
        sparse = root / "sparse"
        with sparse.open("wb") as stream:
            stream.truncate(50_000_000)
        actual = footprint([sparse])
        assert actual["logical_bytes"] == 50_000_000
        assert actual["charged_bytes"] >= 50_000_000
        cases += 1
        (root / "outside-link").symlink_to("/", target_is_directory=True)
        assert footprint([root])["files"] == 3
        cases += 1
        assert footprint([root, original]) == footprint([root])
        cases += 1
    return {"status": "passed", "cases": cases, "native_games": 0}


if __name__ == "__main__":
    import json

    print(json.dumps(run(), sort_keys=True))
