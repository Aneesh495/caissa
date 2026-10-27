"""Semantic controls for private durable blob references and small manifests."""

import json

from tools import storage_archive as original
from tools.storage_archive_anchors import Github, PREFIX


class FakeGithub(Github):
    def __init__(self):
        self.anchors, self.tags, self.refs, self.blobs = {}, {}, {}, {}

    def request(self, method, path, body=None):
        if path == "":
            return {"private": True}
        if method == "POST" and path == "/git/tags":
            oid = original.blob_oid(original.encoded(body))
            self.tags[oid] = {
                "sha": oid,
                "object": {"type": body["type"], "sha": body["object"]},
                "message": body["message"],
            }
            return self.tags[oid]
        if method == "POST" and path == "/git/refs":
            self.refs[body["ref"]] = {
                "ref": body["ref"],
                "object": {"type": "tag", "sha": body["sha"]},
            }
            return self.refs[body["ref"]]
        if path.startswith("/git/ref/"):
            return self.refs["refs/" + path.removeprefix("/git/ref/")]
        if path.startswith("/git/tags/"):
            return self.tags[path.removeprefix("/git/tags/")]
        raise AssertionError("unexpected transport request")

    def get_blob(self, oid):
        return self.blobs[oid]


def reject(function):
    try:
        function()
    except ValueError:
        return
    raise AssertionError("changed archive binding accepted")


def run():
    client = FakeGithub()
    row = {"git_blob": "a" * 40, "sha256": "b" * 64, "bytes": 32}
    oid = client.anchor(row)
    assert client.tags[oid]["object"] == {"type": "blob", "sha": row["git_blob"]}
    assert client.anchor(row) == oid
    cases = 2
    target = client.tags[oid]
    for key, changed in (("type", "tree"), ("sha", "0" * 40)):
        saved = target["object"][key]
        target["object"][key] = changed
        reject(lambda: client.anchor(row))
        target["object"][key] = saved
        cases += 1
    saved = target["message"]
    target["message"] = "another checksum"
    reject(lambda: client.anchor(row))
    target["message"] = saved
    cases += 1
    ref = client.anchors[PREFIX + row["git_blob"]]
    ref["object"]["type"] = "commit"
    reject(lambda: client.anchor(row))
    ref["object"]["type"] = "tag"
    cases += 1
    manifest = original.encoded({"chunks": [row]})
    pin = original.blob_oid(manifest)
    client.blobs[pin] = manifest
    entry = {"path": "packs/example/manifest.json", "sha": pin}
    chunk = {"path": "packs/example/part-00000", "sha": row["git_blob"]}
    commit = original.Github.commit
    captured = []
    original.Github.commit = (
        lambda self, entries, message: captured.append(entries) or "c" * 40
    )
    try:
        assert client.commit([entry, chunk], "example") == "c" * 40
        assert captured == [[entry]]
        cases += 1
        for invalid in (
            [],
            [entry, entry, chunk],
            [entry],
            [entry, dict(chunk, sha="0" * 40)],
        ):
            reject(lambda: client.commit(invalid, "example"))
            cases += 1
    finally:
        original.Github.commit = commit
    return {"status": "passed", "cases": cases, "new_games": 0, "network_calls": 0}


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True))
