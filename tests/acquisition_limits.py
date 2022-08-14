"""Expired acquisition budgets cannot be renewed by process replacement."""

import copy
import json

from training.corpus import enforce_resume_limits


def main():
    limits = {
        "max_seconds": 100,
        "max_child_cpu_seconds": 200,
        "max_gib": 2,
        "min_free_gib": 1,
    }
    first = {
        "event": "started",
        "session": "first",
        "utc_unix": 1000,
        "campaign_wall_origin_unix": 1000,
        **limits,
    }
    finished = {
        "event": "finished",
        "session": "first",
        "stop_reason": "signal-15",
        "child_cpu_seconds_this_session": 50,
    }
    original = [first, finished]
    assert enforce_resume_limits(original, limits, 1050) is None
    tighter = dict(
        limits, max_seconds=90, max_child_cpu_seconds=190, max_gib=1, min_free_gib=2
    )
    assert enforce_resume_limits(original, tighter, 1050) is None
    observed = []

    def rejected(name, history, requested, now, reason):
        before = copy.deepcopy(history)
        try:
            enforce_resume_limits(history, requested, now)
        except ValueError as error:
            assert reason in str(error), (name, str(error))
            observed.append({"case": name, "reason": str(error)})
        else:
            raise AssertionError("expired or enlarged limit accepted: " + name)
        assert history == before

    for key in ["max_seconds", "max_child_cpu_seconds", "max_gib"]:
        rejected(
            key + "-increased",
            original,
            dict(limits, **{key: limits[key] + 1}),
            1050,
            key,
        )
        rejected(key + "-removed", original, dict(limits, **{key: 0}), 1050, key)
    rejected(
        "reserve-reduced", original, dict(limits, min_free_gib=0), 1050, "free-space"
    )
    rejected("elapsed-before-restart", original, limits, 1100, "wall budget")
    rejected(
        "cpu-cumulative",
        [first, dict(finished, child_cpu_seconds_this_session=200)],
        limits,
        1050,
        "child CPU",
    )
    for reason in [
        "wall-time-budget",
        "child-cpu-scheduling-budget",
        "output-byte-budget",
        "preparation-confirmation-timeout",
    ]:
        rejected(
            reason,
            [first, dict(finished, stop_reason=reason)],
            limits,
            1050,
            "already exhausted",
        )
    confirmation = {
        "event": "confirmation-started",
        "session": "first",
        "deadline_unix": 1080,
    }
    assert enforce_resume_limits([*original, confirmation], limits, 1070) == 1080
    rejected(
        "confirmation-cross-session",
        [*original, confirmation],
        limits,
        1080,
        "confirmation budget",
    )
    tightened = [*original, {**first, **tighter, "session": "second", "utc_unix": 1050}]
    rejected("undo-prior-tightening", tightened, limits, 1060, "max_seconds")
    print(
        json.dumps(
            {
                "status": "passed",
                "rejections": observed,
                "admitted": [
                    "same budget",
                    "tighter budget",
                    "same remaining confirmation deadline",
                ],
                "full_acceptance": False,
            }
        )
    )


if __name__ == "__main__":
    main()
