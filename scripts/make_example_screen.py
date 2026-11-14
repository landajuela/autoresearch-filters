"""Regenerate data/example_screen.csv: a synthetic table in the shape users arrive with.

Computed columns plus one experimental outcome, no ID and no group column. The latent
quality is deliberately visible in some columns and absent from others, so a search has
something real to find and something real to reject. This is a fixture, not evidence.
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROWS = 240
SEED = 20261114


def main() -> Path:
    rng = np.random.default_rng(SEED)
    quality = rng.normal(size=ROWS)  # the latent property no column measures directly

    def noisy(weight: float) -> np.ndarray:
        return weight * quality + np.sqrt(max(1 - weight**2, 0.0)) * rng.normal(size=ROWS)

    frame = pd.DataFrame(
        {
            # Informative, and the two strongest partly duplicate each other.
            "docking_energy": (-38 - 6.5 * noisy(0.62)).round(2),
            "predicted_affinity": (6.4 + 0.75 * noisy(0.55)).round(3),
            "shape_complementarity": np.clip(0.62 + 0.09 * noisy(0.38), 0, 1).round(3),
            # Weak, and one column carries nothing at all.
            "rmsd_to_model": np.abs(1.6 - 0.7 * noisy(0.18)).round(2),
            "polar_contacts": np.clip(np.round(7 + 2.6 * noisy(0.15)), 0, None).astype(int),
            "strain_energy": np.abs(14 + 5.5 * rng.normal(size=ROWS)).round(2),
        }
    )
    # Measured outcome: a noisy threshold on the latent quality, about 30% successes.
    chance = 1 / (1 + np.exp(-(2.1 * quality - 1.05)))
    frame["measured_binding"] = (rng.random(ROWS) < chance).astype(int)

    path = Path(__file__).resolve().parents[1] / "data/example_screen.csv"
    frame.to_csv(path, index=False)
    print(f"Wrote {path}: {len(frame)} rows, {frame.measured_binding.sum()} successes")
    return path


if __name__ == "__main__":
    main()
