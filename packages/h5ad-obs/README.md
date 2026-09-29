# h5ad-obs

Reads the `obs` table out of a remote `.h5ad` by fetching only the byte ranges
that back it. `X`, `layers`, `obsm`, `var` and `raw` are never read.

Works against any host honouring HTTP range requests — GCS, S3, Sanger COG,
CELLxGENE's CDN, plain static hosts.

```sh
uvx --from "git+https://github.com/Cellular-Semantics/atlas-skills@v0.2.0#subdirectory=packages/h5ad-obs" \
    h5ad-obs https://datasets.cellxgene.cziscience.com/<id>.h5ad --list-columns
```

stdout is a JSON summary including byte accounting; the obs table itself goes to
`--out` (parquet by default) because it is usually large.

## Profiling

`--profile` prints a per-column summary — storage kind, cardinality, and sample
values — instead of reading obs. It is what an agent needs to decide *what a
column is*.

```sh
h5ad-obs <url> --out obs.parquet       # one remote read
h5ad-obs obs.parquet --profile text    # free; also accepts .csv / .tsv
h5ad-obs <url> --profile               # JSON, straight off the wire
```

```
name | kind | n_unique | sample values
BICCN_cluster_label | categorical[33 cats] | 33 | 'Vip', 'L4', 'Ndnf', 'Pvalb', ...
major_dissection | categorical[1 cats] | 1 (constant) | 'V1', 'V1', 'V1', ...
total_reads | array int64 | 1679 | 23770190, 18388503, 20515208, ...
```

Sample values are **spread across the table, not taken from the head**: obs is
routinely sorted by donor or cluster, and the first twenty rows of a sorted
column show one value. `(constant)` means the cardinality is known exactly and
is one — always determinable for a categorical, and for anything else only when
every row was scanned (`--scan-rows`, default 2000).

Profiling a URL reads less than a full obs read, but not by much, so it is
rarely worth a second trip to the network:

| obs | `--profile` | full obs |
|---|---|---|
| 1,679 x 37 | 1.3 MB, 5 requests | 1.3 MB, 5 requests |
| 115,282 x 34 | 12.6 MB, 6 requests | 16.8 MB, 8 requests |
| 2,282,447 x 70 | 180 MB, 86 requests | 306 MB, 146 requests |

Read obs once and profile the file, unless obs has millions of rows and you want
very few columns.

## Cost

On a 476 MB atlas, all 51 obs columns cost 13 range requests and 27.3 MB in
~8-13 s. The floor is ~21 MB because HDF5 metadata is scattered through the file
and must be walked before any column is readable — **reading one column costs
nearly as much as reading all of them**, so pull the whole table once and subset
locally.

`--block-size` trades bytes against round trips. The default of 2 MB suits large
files; on a small one it overshoots badly. On a 30.6 MB CELLxGENE dataset:

| `--block-size` | requests | fetched | % of file |
|---|---|---|---|
| 2 (default) | 5 | 10.5 MB | 34% |
| 0.5 | 6 | 3.1 MB | 10% |
| 0.125 | 9 | 1.2 MB | 3.9% |

## Development

```sh
./dev.sh            # offline suite; runs the whole range-read path against localhost
./dev.sh -m live    # also reads a real dataset over the network
```

The live test resolves a 385-cell CELLxGENE Patch-seq dataset through the
CELLxGENE API at run time, so a revision upstream does not break it. Override
with `H5AD_OBS_LIVE_URL=<url>` to test against your own host.

## Not a portal client

This package takes a URL to a file. Resolving a *portal page* to that URL is a
per-portal job and deliberately lives elsewhere — for CAP, `cap h5ad-url` in the
[cap_skills](https://github.com/Cellular-Semantics/cap_skills) repo:

```sh
h5ad-obs "$(cap h5ad-url https://celltype.info/project/934/dataset/3016 --format text)"
```

Handing a known portal URL to `h5ad-obs` fails immediately with a message saying
what to run instead, rather than trying to parse HTML as HDF5.
