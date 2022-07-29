"""Known rational mixtures, straight-through gradients and legacy identity."""

import json

import numpy as np
import torch

from training.model import deployed_logits


def main():
    torch.set_num_threads(2)
    baseline = torch.tensor([0, 400, -400, 29800, -29800], dtype=torch.float32)
    # Multiples of 1/32 are exact here, including signed half-centipawn ties.
    correction = torch.tensor([0.03125, -0.03125, 0.03125, 4, -4], dtype=torch.float32)
    full = (baseline / 400 + correction).requires_grad_(True)
    if deployed_logits(full, baseline, 100, True) is not full:
        raise ValueError("default objective no longer preserves legacy tensor identity")
    checks = 0
    for weight in [1, 10, 25, 50, 99]:
        actual = deployed_logits(full, baseline, weight, True)
        complete = [13, 387, -387, 29871, -29871]
        expected = []
        for score, base in zip(complete, baseline.tolist()):
            value = score * weight + int(base) * (100 - weight)
            mixed = value // 100 if value >= 0 else -((-value) // 100)
            expected.append(mixed / 400)
        if not torch.allclose(actual, torch.tensor(expected), rtol=0, atol=0.000001):
            raise ValueError(
                "deployed mixture differs at signed rounding/clamping/truncation boundary"
            )
        gradient = torch.autograd.grad(actual.sum(), full, retain_graph=True)[0]
        expected_gradient = torch.tensor([weight / 100] * 3 + [0, 0])
        if not torch.allclose(gradient, expected_gradient, rtol=0, atol=0.000001):
            raise ValueError(
                "mixture straight-through gradient changed its percentage or saturation"
            )
        checks += len(expected)
    # The full initial residual is zero, so changing its deployment weight must
    # preserve the untrained classical baseline rather than weaken the control.
    initial = baseline / 400
    for quantized in [False, True]:
        if not torch.equal(deployed_logits(initial, baseline, 10, quantized), initial):
            raise ValueError("zero residual changed the classical baseline")
    for weight, base in [
        (0, baseline),
        (101, baseline),
        (True, baseline),
        (10, None),
        (10, baseline[:1]),
    ]:
        try:
            deployed_logits(full, base, weight, True)
        except ValueError:
            pass
        else:
            raise ValueError("invalid deployment objective accepted")
    print(
        json.dumps(
            {
                "status": "passed",
                "known_output_comparisons": checks,
                "gradient_percentages": [1, 10, 25, 50, 99],
                "legacy_default_identity": True,
                "zero_residual_classical_unchanged": True,
            }
        )
    )


if __name__ == "__main__":
    main()
