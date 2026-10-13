# Tom Select 2.6.2

Pinned, unmodified browser distribution from the upstream `tom-select@2.6.2`
npm package, fetched through jsDelivr. Apache-2.0 license is included.
No runtime CDN or external script connection is needed.

- Upstream: https://github.com/orchidjs/tom-select
- API: https://tom-select.js.org/docs/api/
- Source: https://cdn.jsdelivr.net/npm/tom-select@2.6.2/dist/js/tom-select.complete.min.js
- CSS: https://cdn.jsdelivr.net/npm/tom-select@2.6.2/dist/css/tom-select.default.min.css
- npm tarball integrity: `sha512-eiXIkk82XzzUTOVQDFpy+ZGejuqdTvMukyUyeZBQaKnqW42UoTiTZnrod/eX0rkqJEc4rZY9DZ3zdjV07i29wQ==`

SHA-256:

| File | SHA-256 |
| --- | --- |
| tom-select.complete.min.js | 8f9d7d3420e938c2c9817818b56df43ea46feae5bf1f5a2e828863c034df0e37 |
| tom-select.default.min.css | b6224cdffdc74a0edd9d4b2f9700b5d2e3a9f4fc19d002d2d07953fc3854a98f |
| LICENSE | f15dc64ea1f373c8af0ee7c020064360497addf335c9c2bcf27c3a6f56a6f0bd |

`workspace-select.js` owns the native form integration, popup positioning,
IME commit protection and dynamic catalog synchronization. Library code owns
combobox/listbox keyboard behavior. `workspace-select.css` maps to existing
Finance-aligned tokens. Run `tools/verify_workspace_select_browser.mjs` after
upgrading either the library or adapter.
