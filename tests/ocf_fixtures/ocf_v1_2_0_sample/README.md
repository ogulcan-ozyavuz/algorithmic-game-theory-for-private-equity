# OCF v1.2.0 official sample (verbatim subset)

Copied byte-for-byte from the Open Cap Table Coalition repository at tag `v1.2.0`
(commit `9f987b48e288703ff2cd6c4534f7769bb04e724a`):
<https://github.com/Open-Cap-Table-Coalition/Open-Cap-Format-OCF/tree/v1.2.0/samples>

Copyright © 2024 Open Cap Table Coalition. The OCF licence (`LICENSE.md`, "Schema and
Documentation License v1.0.1") licenses sample OCF JSON files as "Code Components" under
the Apache License 2.0.

Only the five files `ovf.ocf` opens are included. The manifest also lists legend,
vesting-terms, valuation and financing files; the reader records those as unread and
never opens them. The manifest's MD5 values are placeholders, as its own `comments`
field says, so `verify_md5=True` rejects this package.

`tests/test_ocf.py` uses this package to show, in order, why a strict reading refuses it.
