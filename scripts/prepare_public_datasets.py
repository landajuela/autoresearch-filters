"""Build local, auditable benchmark tables from the public dataset survey.

Run from the repository root. Downloads and generated tables live in ignored
data/raw/<dataset>/. Tables and audits go in data/prepared/<config-name>/.
This script never opens campaign data, fits a
model, selects signals by observed performance, or runs verify/final.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/raw"
OUT = ROOT / "data/prepared"

# Directions are physical/model conventions, fixed before baseline evaluation.
STABILITY_SIGNALS = {
    "score_per_res": ("lower", "Rosetta total energy per residue; lower energy is preferred."),
    "pack": ("higher", "Rosetta packing quality; tighter packing is preferred."),
    "worstfrag": ("lower", "Worst local fragment deviation; smaller deviation is preferred."),
    "exposed_hydrophobics": ("lower", "Exposed hydrophobic surface; less exposure is preferred."),
    "buried_np_AFILMVWY_per_res": (
        "higher",
        "Buried nonpolar surface per residue; more burial is preferred.",
    ),
    "fa_rep_per_res": ("lower", "Repulsive energy per residue; fewer clashes are preferred."),
    "hbond_sc": ("lower", "Side-chain hydrogen-bond energy; more favorable energy is preferred."),
}


def csv(group: str, name: str) -> pd.DataFrame:
    return pd.read_csv(DATA / group / name, low_memory=False)


def write_dataset(name, frame, signals, baseline, notes, source_rows):
    """Check schema and save data and its interpretation before any evaluation."""
    directory = OUT / name
    if directory.exists():
        raise FileExistsError(f"Refusing to overwrite prepared dataset: {directory}")
    path = directory / "candidates.csv"
    required = ["candidate_id", "group", "success", *signals]
    frame = frame[required].copy()
    if frame.candidate_id.isna().any() or frame.candidate_id.duplicated().any():
        raise ValueError(f"{name}: missing or duplicate candidate IDs")
    if frame.group.isna().any() or frame.success.isna().any():
        raise ValueError(f"{name}: missing group or outcome")
    if set(frame.success.unique()) != {0, 1}:
        raise ValueError(f"{name}: outcome must contain both binary classes")
    for col in signals:
        frame[col] = pd.to_numeric(frame[col], errors="raise")
        if np.isinf(frame[col]).any():
            raise ValueError(f"{name}: infinite oracle {col}")
        if frame[col].nunique() < 2:
            raise ValueError(f"{name}: constant oracle {col}")
    missing = frame[list(signals)].isna().sum().to_dict()
    # Missing computed values are handled by the configuration's drop policy.
    complete = frame.dropna(subset=list(signals))
    counts = complete.groupby("group").success.agg(["size", "sum"])
    last = str(sorted(counts.index)[-1])
    if not 0 < counts.loc[last, "sum"] < counts.loc[last, "size"]:
        raise ValueError(f"{name}: alphabetical holdout {last!r} lacks both classes")
    directory.mkdir(parents=True)
    frame.to_csv(path, index=False)
    summary = {
        "name": name,
        "source_rows": int(source_rows),
        "prepared_rows": len(frame),
        "complete_rows": len(complete),
        "positives": int(complete.success.sum()),
        "groups": len(counts),
        "holdout_group": last,
        "signals": signals,
        "baseline": baseline,
        "missing_signal_rows": {k: int(v) for k, v in missing.items()},
        "notes": notes,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    (directory / "audit.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: summary[k]
                for k in [
                    "name",
                    "source_rows",
                    "prepared_rows",
                    "complete_rows",
                    "positives",
                    "groups",
                    "holdout_group",
                ]
            }
        ),
        flush=True,
    )


def overath():
    d = csv("overath", "prepared_training_dataset.csv")
    signals = {
        "af3_ipSAE_min": ("higher", "AF3 minimum directional interface confidence."),
        "af3_iptm_avg": ("higher", "AF3 mean interface predicted TM-score."),
        "af2_pae_interaction": ("lower", "AF2 predicted interface alignment error."),
        "colab_ipSAE_min": ("higher", "ColabFold minimum directional interface confidence."),
        "boltz1_ipSAE_min": ("higher", "Boltz-1 minimum directional interface confidence."),
        "af3_rosetta_interface_sc": ("higher", "Shape complementarity of the predicted interface."),
        "af3_rosetta_interface_dG_SASA_ratio": (
            "lower",
            "Rosetta interface energy per buried surface area.",
        ),
        "af3_sap_binder": ("lower", "Predicted binder spatial aggregation propensity."),
    }
    d = d.rename(columns={"binder_id": "candidate_id", "target_id": "group", "binder": "success"})
    write_dataset(
        "public-overath",
        d,
        signals,
        "af3_ipSAE_min",
        [
            "Published binary binder labels are retained without a new affinity threshold.",
            "The pinned table contains 3,760 rows, versus 3,766 in the paper title.",
            "Binder IDs are unique; this table does not contain binder sequences, so "
            "sequence-level deduplication was not verified.",
            "The dataset includes Cao/Bennett designs: these campaigns are overlapping "
            "benchmarks, not independent replication.",
            "Only the eight declared computed signals are eligible; experimental fields, IDs, "
            "source names and all other columns are excluded.",
        ],
        len(d),
    )


def bits_to_binders():
    m = csv("bits-to-binders", "12k_all_metrics.csv")
    r = csv("bits-to-binders", "12k_all_results.csv")
    joined = m.merge(r, on="global_id", validate="one_to_one", suffixes=("", "_experiment"))
    if len(joined) != len(m) or len(joined) != len(r):
        raise ValueError("Bits to Binders: incomplete join")
    if not joined.sequence.eq(joined.sequence_experiment).all():
        raise ValueError("Bits to Binders: sequences disagree across files")
    if not joined.team.eq(joined.team_experiment).all():
        raise ValueError("Bits to Binders: team metadata disagree")
    signals = {
        "boltz_A_BC_max_ipSAE": (
            "higher",
            "Maximum Boltz interface confidence against the target subchains.",
        ),
        "chai1_A_BC_max_ipSAE": (
            "higher",
            "Maximum Chai interface confidence against the target subchains.",
        ),
        "boltz_rosetta_A_BC_iptm": ("higher", "Boltz binder-target interface predicted TM-score."),
        "boltz_plddt_binder_none": ("higher", "Boltz predicted binder local confidence."),
        "boltz_rosetta_A_BC_dG_separated/dSASAx100": (
            "lower",
            "Rosetta binder-target binding energy per buried surface area.",
        ),
        "boltz_sap_score": ("lower", "Predicted spatial aggregation propensity."),
        "esm2_binder_LL_target": ("higher", "ESM2 binder log likelihood in target context."),
    }
    keep = (
        joined.fourclass.isin(["Up", "Down", "Not Sig"])
        & joined.leah_12k_twist_dna_detected
        & joined.team.ne("Leah_labs")
    )
    d = joined.loc[keep].copy()
    d["success"] = d.fourclass.eq("Up").astype(int)
    d["candidate_id"] = "b2b:" + d.global_id.astype(str)
    d["group"] = d.team
    write_dataset(
        "public-bits-to-binders",
        d,
        signals,
        "boltz_A_BC_max_ipSAE",
        [
            "Outcome is the published Up enrichment call versus Down/Not Sig among recovered, "
            "DNA-detected designs; it is not an affinity or clinical-efficacy label.",
            "Not Recovered rows and DNA synthesis failures are excluded rather than relabeled "
            "as nonbinders.",
            "Leah_labs entries are excluded as organizer controls; the 28 competitor teams "
            "define groups.",
            "Joins require matching unique global_id, sequence and team; experimental counts, "
            "FDR, logFC and all other measured columns are excluded from signals.",
            "Team holdout tests transfer between design teams for CD20, not to new targets. "
            "Sequence relatives can remain within teams.",
            "Rosetta shape-complementarity fields are excluded because they are constant zero "
            "in this release; the seven retained oracle directions were declared before "
            "evaluation.",
        ],
        len(joined),
    )


def stability(which):
    if which == "linsky":
        d = csv("linsky", "sc16_combined_all.csv")
        seq = "sequence"
        outcome = ["tryp_stability", "chymo_stability"]
        cutoff = 0.5
        d["group"] = d.fold
        coil = d.description.str.contains(r"(?:^|_)coil[CM]_", regex=True)
        d.loc[d.group.isna() & coil, "group"] = "coil"
        notes = [
            "Published label: both trypsin and chymotrypsin stability scores strictly exceed 0.5.",
            "The released combined table encodes five fold groups plus coil; coil is recovered "
            "from design names where fold is missing. The paper describes eight folds, so this "
            "export is not claimed to cover every paper cohort.",
        ]
    else:
        d = csv("rocklin", "rocklin_combined_scores_21.csv")
        seq = "sequence_x"
        outcome = ["stabilityscore_t", "stabilityscore_c"]
        cutoff = 1.0
        if not d.description.str.match(r"^(?:HHH|EHEE|HEEH|EEHEE)_rd[1-4]_\d+_0001$").all():
            raise ValueError("Unexpected Rocklin control/variant identifiers")
        d["group"] = d.description.str.split("_").str[0]
        notes = [
            "Published stringent label: both protease stability scores strictly exceed 1.0; "
            "the later Linsky notebook's 0.5 relabeling is not used for this campaign.",
            "This is the Rocklin design-only table re-scored and redistributed by the Linsky "
            "authors, not all natural proteins, mutants and controls in Rocklin's original "
            "experiment.",
        ]
    original = len(d)
    d = d.dropna(subset=[seq, "group", *outcome]).copy()
    if (d.groupby(seq).group.nunique() > 1).any():
        raise ValueError("Identical sequence assigned to different folds")
    # A deterministic representative structure is chosen without reading scores.
    # Repeated experimental measurements are reduced by the predeclared median.
    ordered = d.sort_values("description", kind="stable")
    first = ordered.drop_duplicates(seq).set_index(seq)
    medians = d.groupby(seq)[outcome].median()
    first[outcome] = medians.reindex(first.index)
    first["success"] = first[outcome].gt(cutoff).all(axis=1).astype(int)
    first["candidate_id"] = [
        which + ":" + hashlib.sha256(s.encode()).hexdigest() for s in first.index
    ]
    notes += [
        "Rows with missing measured stability are removed before label construction.",
        "One candidate per exact amino-acid sequence. Repeated protease measurements are "
        "summarized by their median; structural features come from the lexicographically first "
        "description, with source order breaking ties. No best score or favorable replicate is "
        "selected.",
        "Seven physical descriptors are allowlisted. The unsat_hbond column is excluded "
        "because every entry is the constant sentinel 911. Experimental EC50s, cleavage-model "
        "outputs used to derive the outcome, IDs and all other columns are excluded.",
        "Exact duplicates are removed, but sequence-homology clustering is not performed. Fold "
        "groups are used for the holdout and discovery cross-validation.",
    ]
    write_dataset(
        "public-" + which,
        first.reset_index(drop=True),
        STABILITY_SIGNALS,
        "score_per_res",
        notes,
        original,
    )


def cao_bennett():
    signals = {
        "pae_interaction": ("lower", "AF2 predicted interface alignment error."),
        "af2_complex_rmsd": ("lower", "AF2/design complex structural disagreement."),
        "score_per_res": ("lower", "Rosetta monomer energy per residue."),
        "ddg": ("lower", "Rosetta predicted binding energy."),
        "rf2_pae_interaction": ("lower", "RoseTTAFold2 predicted interface alignment error."),
        "plddt_binder": ("higher", "AF2 predicted binder local confidence."),
        "interface_lddt": ("higher", "DeepAccuracyNet predicted interface accuracy."),
        "contact_molecular_surface": ("higher", "Computed molecular contact surface."),
    }
    member = "supplemental_files/figure_data/retrospective_analysis/af2_rmsd_graphs1_data.sc"
    with tarfile.open(DATA / "cao-bennett/scripts_and_main_pdbs.tar.gz") as archive:
        stream = archive.extractfile(member)
        if stream is None:
            raise ValueError(f"Missing archive member: {member}")
        d = pd.read_csv(
            stream, sep=r"\s+", usecols=["description", "target", "binder_4000_nm", *signals]
        )
    original = len(d)
    d = d.dropna(subset=["description", "target", "binder_4000_nm"]).copy()
    if not set(d.binder_4000_nm.unique()) <= {True, False}:
        raise ValueError("Unexpected published binder labels")
    d = d.drop_duplicates()
    if d.duplicated(["target", "description"]).any():
        raise ValueError("Duplicate Cao/Bennett target/design identifiers require investigation")
    d["candidate_id"] = d.target + ":" + d.description
    d["group"] = d.target.replace({"IL7Ra_graft": "IL7Ra"})
    d["success"] = d.binder_4000_nm.astype(int)
    write_dataset(
        "public-cao-bennett",
        d,
        signals,
        "pae_interaction",
        [
            "Retrospective Cao design screen re-scored by Bennett, using the release's "
            "binder_4000_nm calls (paper criterion SC50 < 4 micromolar). No censored "
            "experimental bound is used as a signal.",
            "The archive's prospective figure table contains only 9,999 rows, two targets and "
            "one positive. It is not treated as the complete prospective screen or prepared as "
            "a separate campaign.",
            "The eight declared computed scores are allowlisted. Experimental bounds, barcode "
            "counts, confidence flags about the assay, alternative labels, topology, target "
            "and IDs are excluded from rule terms.",
            "No binder sequence column is present in this table. Target/design IDs are checked "
            "for uniqueness; sequence-level duplication is not established.",
            "Overath contains a subset of this source: do not treat the two campaigns as "
            "independent validation.",
            "IL7Ra_graft and IL7Ra share the IL7Ra target group; the graft cohort is not a "
            "distinct biological target. Original target strings remain in candidate IDs.",
            "Exact duplicate rows across the ID, label and all eight selected signals are "
            "collapsed; conflicting repeated target/design IDs cause preparation to stop.",
        ],
        original,
    )


def initialise(name, uv):
    directory = OUT / name
    spec = json.loads((directory / "audit.json").read_text())
    signals = spec["signals"]
    config_path = ROOT / "configs" / f"{name}.json"
    if config_path.exists():
        raise FileExistsError(f"Refusing to overwrite config: {config_path}")
    command = [
        uv,
        "run",
        "--cache-dir",
        "/tmp/autoresearch-uv-cache",
        "filters",
        "init",
        "--data",
        str((directory / "candidates.csv").relative_to(ROOT)),
        "--name",
        name,
        "--label",
        "success",
        "--success",
        "1",
        "--id",
        "candidate_id",
        "--group",
        "group",
        "--signals",
        ",".join(signals),
        "--baseline-signal",
        spec["baseline"],
        "--higher",
        ",".join(k for k, v in signals.items() if v[0] == "higher"),
        "--lower",
        ",".join(k for k, v in signals.items() if v[0] == "lower"),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    (directory / "init.log").write_text(result.stdout + result.stderr)
    print(result.stdout, end="", flush=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    config = json.loads(config_path.read_text())
    if set(config["signals"]) != set(signals):
        raise ValueError("init unexpectedly omitted a declared oracle")
    for key, (direction, description) in signals.items():
        if config["signals"][key]["direction"] != direction + "_is_better":
            raise ValueError(f"Direction mismatch: {key}")
        config["signals"][key]["description"] = description
    # Choose PR-AUC for rare-hit retrieval before evaluating the baseline.
    config["protocol"]["primary_metric"] = "pr_auc"
    config_path.write_text(json.dumps(config, indent=2) + "\n")


def proteingym():
    """Use published zero-shot scores; validate every label against the DMS archive."""
    signals = {
        "ESM2_650M": ("higher", "Published ESM2-650M zero-shot variant-effect score."),
        "ESM1v_ensemble": ("higher", "Published ESM1v ensemble zero-shot variant-effect score."),
        "ProteinMPNN": ("higher", "Published ProteinMPNN inverse-folding log likelihood."),
        "ESM-IF1": ("higher", "Published ESM-IF1 inverse-folding log likelihood."),
        "GEMME": ("higher", "Published GEMME evolutionary variant-effect score."),
    }
    reference = csv("proteingym", "DMS_substitutions.csv")
    convention = json.loads((DATA / "proteingym/config.json").read_text())[
        "model_list_zero_shot_substitutions_DMS"
    ]
    if any(convention[s]["directionality"] != 1 for s in signals):
        raise ValueError("Upstream direction convention changed")
    all_frames = []
    mega_frames = []
    audits = []
    with (
        zipfile.ZipFile(DATA / "proteingym/zero_shot_substitutions_scores.zip") as scores,
        zipfile.ZipFile(DATA / "proteingym/DMS_ProteinGym_substitutions.zip") as assays,
    ):
        for item in reference.sort_values("DMS_id").itertuples():
            filename = item.DMS_filename
            with assays.open("DMS_ProteinGym_substitutions/" + filename) as stream:
                labels = pd.read_csv(stream, usecols=["mutant", "DMS_score_bin"])
            with scores.open(filename) as stream:
                predicted = pd.read_csv(stream, usecols=["mutant", "DMS_score_bin", *signals])
            d = labels.merge(
                predicted, on="mutant", validate="one_to_one", suffixes=("", "_scored")
            )
            if len(d) != len(labels) or len(d) != len(predicted):
                raise ValueError(f"Incomplete ProteinGym join: {filename}")
            if not d.DMS_score_bin.eq(d.DMS_score_bin_scored).all():
                raise ValueError(f"Labels disagree between released archives: {filename}")
            d["candidate_id"] = item.DMS_id + ":" + d.mutant
            d["group"] = item.UniProt_ID
            d["success"] = d.DMS_score_bin.astype(int)
            d = d[["candidate_id", "group", "success", *signals]]
            all_frames.append(d)
            if "Tsuboyama" in item.DMS_id:
                mega_frames.append(d)
            audits.append(
                {
                    "assay": item.DMS_id,
                    "rows": len(d),
                    "group": item.UniProt_ID,
                    "cutoff": item.DMS_binarization_cutoff,
                    "cutoff_method": item.DMS_binarization_method,
                }
            )
            print(
                f"Validated ProteinGym assay {len(audits)}/{len(reference)}: "
                f"{item.DMS_id} ({len(d)} rows)",
                flush=True,
            )
    notes = [
        "ProteinGym v1.3 substitutions: published DMS_score_bin labels retained and checked "
        "against the independent assay archive, with one-to-one joins on assay and mutant.",
        "Five representative zero-shot oracles were fixed in advance: two sequence language "
        "models, two inverse-folding models and one evolutionary model. All five have "
        "higher-is-better direction in the pinned upstream configuration; no supervised model "
        "outputs are used.",
        "Published binary thresholds are assay-specific, often assay medians. Success means "
        "above the published assay cutoff, not a universal biochemical activity threshold.",
        "Groups are UniProt IDs, keeping multiple assays of the same protein together in the "
        "final holdout. Verification remains a random stratified half of the other proteins' "
        "rows, as implemented by this repository; related variants can span discovery and "
        "verification.",
        "Experimental DMS scores, mutation identifiers, assay metadata and all non-allowlisted "
        "model columns are excluded from rule terms.",
        "The MegaScale/ProteinGym campaign below is an overlapping subset, not independent "
        "validation.",
    ]
    full = pd.concat(all_frames, ignore_index=True)
    write_dataset("public-proteingym", full, signals, "ESM2_650M", notes, len(full))
    subset = pd.concat(mega_frames, ignore_index=True)
    write_dataset(
        "public-megascale-proteingym",
        subset,
        signals,
        "ESM2_650M",
        notes
        + [
            "This campaign covers only the 64 Tsuboyama assays included in ProteinGym, with "
            "their existing oracle predictions and published median-based labels. It does not "
            "cover all 776,298 high-quality MegaScale measurements or all 148 designed parent "
            "domains.",
            "The complete original MegaScale measurement archive is downloaded separately. "
            "Experimental inferred dG/ddG values are outcomes, not computational oracles; a "
            "full-MegaScale rule campaign needs additional eligible oracle scores.",
        ],
        len(subset),
    )
    (OUT / "public-proteingym/assay-audit.json").write_text(json.dumps(audits, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "datasets",
        nargs="+",
        choices=["overath", "bits-to-binders", "linsky", "rocklin", "cao-bennett", "proteingym"],
    )
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--uv", default="uv")
    args = parser.parse_args()
    builders = {
        "overath": overath,
        "bits-to-binders": bits_to_binders,
        "linsky": lambda: stability("linsky"),
        "rocklin": lambda: stability("rocklin"),
        "cao-bennett": cao_bennett,
        "proteingym": proteingym,
    }
    for dataset in args.datasets:
        builders[dataset]()
        if args.init:
            initialise("public-" + dataset, args.uv)
            if dataset == "proteingym":
                initialise("public-megascale-proteingym", args.uv)


if __name__ == "__main__":
    main()
