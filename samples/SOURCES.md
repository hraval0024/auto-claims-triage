# Sample image sources and DEV list

Images are NOT committed. They live in `data/samples/` (gitignored). Each entry records the
source page, license and author for attribution.

**DEV images:** any image used to tune or debug the prompt is DEV. The Phase 4 eval must
exclude DEV images (matched by sha256 of the original bytes) or flag them clearly. Every
Phase 1 sample image counts as DEV, because we read their outputs while changing the prompt.

| Local file | Role | sha256 (original bytes) | Source | License | Author | Notes |
|---|---|---|---|---|---|---|
| <a id="altima_accident"></a>`altima_accident.jpg` | DEV | `983673d9642450aa86c9383986506383de653464fecd5398d293601fc4abd39f` | https://commons.wikimedia.org/wiki/File:Altima-Accident.jpg (1920px thumbnail) | CC BY 3.0 | Ryanandlenny | Unedited. Smoke test, caching experiment, F1 regression check. |
