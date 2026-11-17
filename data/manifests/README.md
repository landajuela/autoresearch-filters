# Source manifests

| Dataset | Authoritative manifest | Local raw files |
| --- | --- | --- |
| IgDesign original benchmark | [Packaged IgDesign manifest](../../src/autoresearch_filters/igdesign_manifest.json) | `data/raw/igdesign/` |
| Additional public datasets | [public-datasets.json](public-datasets.json) | `data/raw/<dataset>/` |

IgDesign's manifest lives inside the Python package so its built-in loader works
when installed. Both manifests pin upstream URLs and SHA-256 checksums. Prepared
CSV checksums and import decisions live in `data/prepared/<config-name>/audit.json`.

See the [data catalog](../README.md) and [provenance guide](../PROVENANCE.md).
