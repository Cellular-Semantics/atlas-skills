# h5ad-obs

Reads the `obs` table out of a remote `.h5ad` by fetching only the byte ranges
that back it. `X`, `layers`, `obsm`, `var` and `raw` are never read.

Works against any host honouring HTTP range requests — GCS, S3, Sanger COG,
CELLxGENE's CDN, plain static hosts.

```sh
uvx --from "git+https://github.com/Cellular-Semantics/atlas-skills@v0.1.0#subdirectory=packages/h5ad-obs" \
    h5ad-obs https://datasets.cellxgene.cziscience.com/<id>.h5ad --list-columns
```

stdout is a JSON summary including byte accounting; the obs table itself goes to
`--out` (parquet by default) because it is usually large.

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
