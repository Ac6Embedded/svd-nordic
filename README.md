# svd-nordic

CMSIS SVD files for Nordic Semiconductor devices, pulled from the official
nrfx repository and organized by family. Files are unmodified copies
(provenance: pristine). Every file was parsed with Python xml.etree and has
root element `device`.

## Coverage

| Family | Files |
|--------|-------|
| nRF52  | 7 |
| nRF53  | 2 |
| nRF54H | 6 |
| nRF54L | 16 |
| nRF71  | 5 |
| nRF91  | 2 |
| nRF92  | 7 |
| Total  | 45 |

Total size: about 169 MB.

## Source

* nrfx, https://github.com/NordicSemiconductor/nrfx
* Commit: d58575ae3c27748cabdfaa1ea2b8a386e6425d75 (shallow clone HEAD, fetched 2026-07-19)
* SVDs taken from `bsp/stable/mdk/` in the clone.

## LICENSE AND REDISTRIBUTION STATUS

The nrfx repository ships a single LICENSE file, copied here as
`LICENSES/nrfx-LICENSE.txt`. It carries `SPDX-License-Identifier: BSD-3-Clause`
and starts:

> Copyright (c) 2017 - 2026, Nordic Semiconductor ASA
> All rights reserved.
>
> Redistribution and use in source and binary forms, with or without
> modification, are permitted provided that the following conditions are met: ...

BSD-3-Clause permits redistribution as long as the copyright notice, the
condition list and the disclaimer are kept (they are, in LICENSES/), and the
Nordic name is not used for endorsement.

## Refresh

    python fetch.py

Needs git on PATH and network access. The script re-clones nrfx into .work/,
re-validates every SVD, rebuilds the family folders and manifest.json, then
deletes .work/.

The fetch is incremental: it first compares the upstream HEAD sha against
manifest.json via git ls-remote and downloads only what changed, so an
up-to-date tree costs one metadata request and no clone. A GitHub Action
(.github/workflows/check-updates.yml) runs it weekly on Monday 06:00 UTC
and commits any updates.

## Provenance legend

* pristine: byte-identical copy of the upstream file. All 45 files here are pristine.
* patched, community, converted: not used in this collection.

## Known gaps

* No nRF51 SVDs. The current nrfx `bsp/stable/mdk/` snapshot does not ship any
  nrf51*.svd file, even though older Nordic MDK releases had one. nRF51 is
  end-of-life; take its SVD from an old nRF5 SDK or MDK release if needed.
* nRF54H and nRF71/nRF92 files are per-core (application, radiocore, ppr, flpr,
  and so on), so one chip maps to several files. That is how Nordic ships them.
