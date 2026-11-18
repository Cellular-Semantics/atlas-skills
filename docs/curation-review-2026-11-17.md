# Curation review: the 2026-11 CL_KG snapshot

**Raised from:** re-taking the CL_KG curation snapshot for issue #8 L4. Upstream is
pinned at
[`35dd67b`](https://github.com/Cellular-Semantics/CL_KG/tree/35dd67b7265d816160509b302809e7b423adf6a5/anndata2rdf/src/curated_data)
and the snapshot is recorded in `packages/obs-column-eval/src/obs_column_eval/data/curation/SOURCE.json`.
**Evidence:** the obs column profiles in `evals/fixtures/profiles/`. There are 184: the
73 from 2026-09 and 111 captured on 2026-11-17 with the same reader, `h5ad-obs 0.3.0`.
**Ask:** curator decisions on section 3. Sections 1 and 2 are applied on read, and the
sheets themselves still need the section 1 fix.
**Reported upstream:** [CL_KG#118](https://github.com/Cellular-Semantics/CL_KG/issues/118),
which covers the section 1 fixes, the missing h5ad link (2.3) and the questions in section 3.

> **Resolved upstream, 2026-11-18.** CL_KG fixed #118 in
> [`c2891ee`](https://github.com/Cellular-Semantics/CL_KG/commit/c2891eef8e0c9a1c92cb4aeac187e65f935a8f78),
> and the snapshot is re-pinned there. The body below is the review as written
> against `35dd67b`. What changed:
>
> - **1.1** The sheet now says `Main_cluster_name`. The two `_CORRECTIONS` entries are gone.
> - **1.2** "Colon epithelial" (`5ce42b38`) now has its own h5ad, `ae802158`, which joins
>   l4 with `Celltype`. `b1784014` stays in n73, under "colon immune" only.
> - **1.3, 1.4** The garbled cell and `cel types` are fixed. The `cel types` alias is gone.
> - **2.3** `c7775e88` now has its h5ad link on the Mo_Group sheet. It is `9a305865`,
>   which the Immune sheet already linked and l4 already scored. Both sheets now agree:
>   `author_cell_type`, `initial_clustering`.
> - **3.1** `supercluster_term` is now **cell type** on `0bb62fec` and `9343817c`.
> - **3.2** `predicted.celltype.l2` is now **cell type** on `c2054d78`. Predicted labels
>   count as cell-type columns in this gold set.
>
> Net: l4 is 113 datasets (112 readable, 222 curated cell-type columns), and 185
> profiles. Three readable l4 datasets are "pick nothing" (`4e7af47a`, `d88ee9bc`,
> `e2226a21`, all judged right in section 3). n73 is unchanged, and the frozen baseline
> still re-scores to 0.8289.

> **What changed in the gold set.** 15 sheets, up from 10. The five new ones (Breast,
> Cornea/Limbus/Sclera, Iris/Lens, RPE/Choroid, Retina) were xlsx upstream and are
> converted to CSV at snapshot time. `Curated_nlm-ckn_Datasets_Issue116.csv` is
> **excluded**: it was written from this plugin's own picks (0.4.3), so scoring the
> plugin against it would be circular.
>
> The test set has two tiers:
> - **`n73`** is the 74 datasets behind the published n=73 numbers. Frozen, and unchanged.
>   The frozen predecessor still re-scores to its stored 0.829.
> - **`l4`** is 112 new datasets, 111 of them readable, with 218 curated cell-type
>   columns. It covers every other curated CELLxGENE dataset, one h5ad version each.

---

## 1. Confirmed errors in the sheets

### 1.1 `Main_cluster_names` does not exist in obs. **Applied on read.**

`Curated_data_KG_Mo_Group - KG`, two datasets:

| dataset (h5ad version) | tier | sheet now says | obs has |
|---|---|---|---|
| `5b8941a9-fef8-4348-876c-c333a87c0c3f` | n73 | `Main_cluster_names` | `Main_cluster_name` (77 values: `Retinal progenitors and Muller glia`, `Adrenocortical cells`) |
| `35476cf7-35f1-4daf-8507-734403d09c27` | l4 | `Main_cluster_names` | `Main_cluster_name` (77 values) |

The CL_KG sheet has said `Main_cluster_names` since its last edit (2024-12, `78b47d22`).
It was never right upstream. The 2026-09 snapshot hid this, because its copy of the
sheet had been hand-corrected to `Main_cluster_name` (the "typo correction made after
the original run" in commit `581d4e9`), and the correction was never sent back to
CL_KG. The new snapshot is an exact copy, so the typo came back. Taken as written, it
dropped the frozen baseline from 0.8289 to 0.8253 with no picker involved, and
`test_frozen_baseline_rescores_to_its_stored_value` caught it. The fix now lives in
`curation._CORRECTIONS`, where it is visible, rather than inside a copied CSV.

This is the only name mismatch across the whole test set: every other curated name in
all 184 readable datasets is present in obs, case-sensitively. **Fix upstream:** in
`Curated_data_KG_Mo_Group - KG.csv`, change `Main_cluster_names` to `Main_cluster_name`
on lines 424 and 435.

### 1.2 One h5ad version filed under two CELLxGENE datasets

`b1784014-d30f-4e3a-88d6-65110285d5e4` (n73, `HCA CxG clean V6 - Gut`) appears under both
"colon immune" (`518d9049…`) and "colon epithelial" (`5ce42b38…`). An h5ad belongs to
one dataset, so one of the two links is a copy-paste slip. **It does not move a score:**
both blocks list the same columns (`Celltype` as cell type; `Type`, `Layer`,
`age group`, `biosample_id` as other). The other dataset's own version is simply not in
the sheet. **Which dataset is this file?**

### 1.3 A garbled cell

`c2054d78-3e98-4313-a9e1-60c9a6100bee` (l4, `HCA CxG clean V6 - Immune`) has a column
name typed as `predicted.\ncelltype.l2celltype.l`, with an embedded newline. obs has
`predicted.celltype.l2`. The row is filed as `Other`, so it is not in the cell-type gold
either way. See 3.2 for whether it should be.

### 1.4 A typo in `Content`

The Retina sheet's one cell-type row for `6ad5ca98` reads `cel types`. It is accepted as
cell type on read.

---

## 2. How the snapshot was keyed

### 2.1 One version per CELLxGENE dataset, in l4

The sheets name 202 h5ad versions for 187 CELLxGENE datasets (plus one with no version, 2.3). Two versions of one
dataset are near-duplicates, so l4 keeps one and lists the other under `aliases` in
`manifest.json`:

- **10 versions** belong to datasets that n73 already covers. They add nothing to l4.
- **6 groups** were new datasets with two versions each. The rule: keep a version whose
  curated columns all exist in its obs, and among those the **fullest curation**
  (most cell-type columns, then most rows).

| kept | alias | why |
|---|---|---|
| `504b7a5b` | `02a1eee1` | the alias was curated with 36 rows but **no** cell-type column, though its obs has `cell_group` (`TNK`, `B`, `MonoDC`). The kept version lists `cell_group`, `ct1`–`ct3`. |
| `5b918503` | `16acb1d0` | 3 cell-type columns (`Cell.class`, `Cell.group`, `Lineage`) vs 2 |
| `d901fc14` | `69be948c` | `Cell_type_annotation_level1`–`3` vs level1 only |
| `01a9a94d`, `518edb4f`, `5dc1e511` | `22b59c37`, `a4e81c2f`, `d644d5e0` | identical curation; first by id |

The first three are worth a curator's eye. The same dataset was curated differently on
its two versions, and the gold set now takes the fuller reading.

### 2.2 n73 holds four datasets twice. **Left as is.**

n73 scores both versions of `ebc2e1ff`, `de2c780c`, `218acb0f` and `2a498ace`, which is 8
entries for 4 datasets. That is what the published 0.940 was measured on, so the tier
stays frozen. The entries now name each other under `aliases`. **How a combined
n73 + l4 figure should treat them is for the eval design to settle.**

### 2.3 Not scorable

- `c7775e88-49bf-4ba2-a03b-93f00447c958` (Mo_Group, COVID-19 immune response) has
  15 rows, including `author_cell_type` and `initial_clustering` as cell type, but **no
  h5ad link**. The gold set is keyed by h5ad version, so it cannot be used. Adding the
  link would make it scorable.
- `3006a39e-5be2-477a-b18f-13d8cd6a0194` (l4, Gut) returns **HTTP 403** from the CDN,
  the same as `b1b7e4e0` in n73. It is kept in the manifest and recorded under
  `PROVENANCE.missing`.

---

## 3. "Pick nothing" expectations to confirm

A curated dataset with no cell-type row is scored as "the right answer is to pick
nothing". It is a real case, but only if the curator looked and found nothing. Six
readable l4 datasets are in that position. Two look right, four want a decision.

| dataset | sheet | rows recorded | cell-type-like columns in obs | read |
|---|---|---|---|---|
| `4e7af47a` | Immune | `batch`, `temp` | none | **looks right** |
| `d88ee9bc` | Gut | a row with no column | none | **looks right** |
| `e2226a21` | Immune | a row with no column | none | **looks right** |
| `0bb62fec` | Brain | 9, incl. `supercluster_term` as other | `supercluster_term` (21: `Upper rhombic lip`, `Thalamic excitatory`, `Splatter`) | **3.1** |
| `9343817c` | Brain | 9, incl. `supercluster_term` as other | `supercluster_term` (10: `Oligodendrocyte`, …) | **3.1** |
| `c2054d78` | Immune | `pool_number`, the garbled 1.3 | `predicted.celltype.l2` (31: `CD4 TCM`, `NK`, `Treg`) | **3.2** |

### 3.1 `supercluster_term` in the Siletti brain atlas

Both datasets record `supercluster_term` and file it as **other**. Its values include
cell classes (`Oligodendrocyte`, `Thalamic excitatory`) alongside anatomical-lineage
names (`Upper rhombic lip`) and `Splatter`. No dataset in either tier curates it as
cell type. **Question:** is it out because it is a mixed taxonomy level, or an
oversight? If it is out, these stay "pick nothing", and a picker that takes it will be
marked wrong on two datasets.

### 3.2 Predicted labels again

This is the open question from the 2026-09 review, section 3.2, in a new place.
`predicted.celltype.l2` is an Azimuth prediction, not an author assertion. Curating it
as other would settle `c2054d78` as "pick nothing". A "predicted cell type" `Content`
value would settle it and the HLCA cases together.

---

## 4. Found after the upstream fix

### 4.1 A curated column that is constant in obs. **Open; not changed on read.**

`5dc1e511` (l4, `Curated_Breast_Data_KG_V2`, breast immune cells, 25,382 cells)
curates `level0`, `level1`, `level1_global` and `level2`. In obs, `level1_global`
is **constant**: `Immune` in every cell. It is the only curated cell-type column
in all 185 readable datasets that does not vary.

It looks like a slip copied from the sibling dataset. On `4484426f` (breast
stroma) the same sheet curates `level1_global`, which varies there (4 values), and
leaves out `level0_global`, which is constant there. So the curators skip constant
columns elsewhere in this sheet.

It matters because the picker's rule 4 rejects constant columns. As curated, a
picker following its rules scores at most 0.75 on this dataset. Scores below take
the sheet as written. **Question for the curators:** drop `level1_global` from
`5dc1e511`? Because of this, the light subset uses `4484426f` as its breast case.

### 4.2 A doublet flag curated as cell type. **Open; not changed on read.**

`ac9c13da` (l4, `HCA CxG clean V6 - Immune`, rheumatoid arthritis) curates
`rough_annot`, `fine_annot` **and `scrub_doublets`** as cell type.
`scrub_doublets` is a boolean (`False`/`True`), the output of a doublet
detector. The picker takes the first two and leaves it out (J = 0.67).
**Question:** should `scrub_doublets` be `Other`?

### 4.3 A curated `author_cell_type` that holds only numbers. **Open; not changed on read.**

`7e07419c` (l4, Retina sheet) curates `author_cell_type`. Its 27 values are
`'1.0'` … `'27.0'`, cluster numbers with no names. The picker's rule 3 rejects
number-only columns, so it picks nothing and scores 0. This is the only l4 miss.
The gold is not wrong as such: the column is what the authors submitted as their
cell type. But the labels behind the numbers are not in the file. **Question:**
keep it as cell type? If so, rule 3 may need an exception for a column the
authors *named* as their cell type. That would be a picker change, scored against
n73 as well.
