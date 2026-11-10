# Sample image sources and DEV list

The source of truth is `samples/manifest.json`: title, file page, image URL, license, author
and sha256 for every sample, filled in from Wikimedia metadata by `scripts/fetch_samples.py`.
Images are never committed; they are downloaded to `data/samples/` (gitignored).

**DEV images:** any image used to tune or debug the prompt is DEV. **Every entry in the
manifest is DEV.** The Phase 4 eval must exclude them by sha256, or flag them clearly.

**Not clean-licensed:** `case7_screenshot` is the candidate's own screenshot of a third-party
web page. It is local test input only and is never committed or redistributed.
