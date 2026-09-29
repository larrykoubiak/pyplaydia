# PlaydiaEmu

The AK8000 coefficient table and decoding/reconstruction rules in
`playdia_codec/tables.py`, `codec.py`, and `transform.py` are adapted from
[PlaydiaEmu](https://github.com/AloysHF/PlaydiaEmu), revision
`6e75840`, particularly `crates/playdiaemu-core/src/video/ak8000.rs`.

Copyright (c) 2026, Aloys (AloysHF).

The upstream BSD 3-Clause license is retained in
[LICENSES/PlaydiaEmu-BSD-3-Clause.txt](LICENSES/PlaydiaEmu-BSD-3-Clause.txt).
PlaydiaEmu recovered the run/level mapping, implicit block endings, DC
prediction, and working 4×4 DCT reconstruction. This Python implementation
builds on that work and pyplaydia's earlier disc and packet research.
