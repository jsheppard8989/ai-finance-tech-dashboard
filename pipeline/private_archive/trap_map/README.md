# Trap Map historical archive — Nov 5, 2026

Retired from the public site by the Nov 5, 2026 10:10 PM CT decision.

- `trap_map.json`: complete unchanged record set, including open and closed rows, entry evidence, stops, modeled/stated exits, histories, totals and original SPY lots.
- `trap-map.html`: byte-identical final rendered page.
- `index.html`: byte-identical final pre-removal home page, including the generated strip. This is a historical build output, not a live homepage.
- `sources/*.snapshot`: original generator, fetcher, validator, sync/repricing tools, workflows, guard and related tests before path changes; inert text snapshots, not another test suite.
- `portfolio.json`: byte-identical frozen public healthcare basket source; the public copy remains at `site/data/portfolio.json`, without further repricing.
- `manifest.json`: original commit, capture time, row ids, exact totals and SHA-256 checksums.

The preserved source snapshot is after PR #766's Nov 5 evening price refresh. Six positions remained open; CEG and LRCX were closed. Records are frozen, not automatically repriced. The build/validator defaults now target this archive only. The quote-pull command is retired. All source research and other historical artifacts elsewhere in the repository remain intact.

## Privacy boundary
This directory is outside `site/` and excluded from the GitHub Pages artifact. **The GitHub repository is PUBLIC, so these files and prior Git history are still publicly readable through GitHub.** This is not an authenticated private site or a paid product. No repository visibility or access policy was changed.
