# Dataset Versioning

Datasets are registered by `dataset_id`. Each registration creates the next immutable version (`v1`, `v2`, ...), computes a schema hash, computes a deterministic data hash, writes a source manifest, and stores a local copy under the ignored data lake dataset directory.

Snapshots copy the latest registered version into `data/lake/snapshots/` and write JSON metadata. Version diffs report schema changes, data hash changes, and row-count deltas. These controls support reproducible research, but they do not certify data for live trading.
