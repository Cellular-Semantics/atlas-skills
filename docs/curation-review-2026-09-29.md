# Curation review: cell-type column coverage in the CL_KG sheets

**Raised from:** the `author-annotation-columns` benchmark, full run 2026-09-29, n=73
CELLxGENE datasets.
**Evidence:** `docs/benchmark-results.json`, obs column profiles in
`evals/fixtures/profiles/`.
**Ask:** decisions on the remaining items in "Policy questions". Sections 1 and 2 were
reviewed on 2026-09-29 and are settled — see the status on each.

> **Status after review.** Sections 1, 2.1 and 2.2 are **accepted and applied**; 2.3 and
> 2.4 are **declined**. The accepted changes are applied on read in
> `obs_column_eval.curation` (`_CORRECTIONS`, `_ADDITIONS`) so the shipped CSVs stay
> a faithful copy of the CL_KG sheets — **the sheets themselves still need updating**,
> which is what this document is for. Section 3 is open.
>
> Re-scoring against the revised gold set moved the benchmark from Jaccard 0.926 to
> **0.940** and precision from 0.944 to **0.958**. The frozen predecessor moved by the
> same amount (0.815 → 0.829), so the delta between them is unchanged at +0.111 — the
> correction favours neither, which is what a correction should do.

The picker agrees exactly with curation on 62 of 73 datasets. This is about the other
11. Most are not picker errors — they are columns the picker found that curation does
not list, and on inspection several of those columns do hold author cell-type labels.

Sample values below are taken from the committed obs profiles, spread across the table.

---

## 1. Confirmed errors in the sheets

### 1.1 Four capitalised column names that do not exist in obs — **ACCEPTED, applied**

`ac818189-5c6b-48d2-8bf1-f7511de7b5a9` (HCA CxG clean V6 - Immune)

| sheet says | obs actually has |
|---|---|
| `Cell_type_original` | `cell_type_original` |
| `Cell_type_source` | `cell_type_source` |
| `Cluster` | `cluster` |
| `Cluster_source` | `cluster_source` |

obs column names are case-sensitive, so as written these name nothing. Anyone using the
sheet to pull columns gets a `KeyError`.

This was the only such fault across all 186 curated cell-type column names, which is a
good hit rate for hand curation. Corrected on read in
`obs_column_eval.curation._CORRECTIONS`, and a test fails if another appears.
**The sheet itself still needs fixing.**

This alone took the dataset from Jaccard 0.18 to 0.44; the rest of its gap is the
composite-column question in 3.1.

---

## 2. Columns that appear to be missing from curation

Each of these holds per-cell values that read as cell-type labels, and none is listed.

### 2.1 HLCA pre-harmonisation annotations — **ACCEPTED, all seven added**

`b13072bd-9cb6-42ca-9f4f-01252baef273`, `b351804c-293e-4aeb-9c4c-043db67f4540`

Curated: `ann_level_1`…`ann_level_5`, `ann_finest_level` — the *harmonised* hierarchy.

Not curated, but present and cell-type-valued:

| column | n | sample |
|---|---|---|
| `original_ann_level_1` | 8 | `Immune`, `Endothelial`, `Epithelial` |
| `original_ann_level_2` | 15 | `Myeloid`, `Lymphoid`, `Airway epithelium` |
| `original_ann_level_3` | 35 | `Macrophages`, `T cell lineage`, `AT2`, `Basal` |
| `original_ann_level_4` | 78 | `Alveolar macrophages`, `Club` |
| `original_ann_level_5` | 33 | `Alveolar Mph MT-positive`, `NK CD16` |
| `original_ann_nonharmonized` | 816 | `Alveolar epithelial type 2 cells` |
| `ann_coarse_for_GWAS_and_modeling` | 39 | `Alveolar macrophages`, `DC2`, `T cell lineage` |

These are the contributing studies' own annotations, before harmonisation — arguably
*more* "author-provided" than the harmonised levels that are curated. Between them these
two datasets account for a large share of the benchmark's remaining precision loss.

**Accepted.** All seven added to both datasets. `b13072bd` went from Jaccard 0.32 to
0.68 and `b351804c` from 0.43 to 0.93; between them this is most of the improvement in
measured precision. Their residual gap is `scanvi_label` and `transf_ann_level_*`, which
are section 3.2 and still open.

### 2.2 An author-asserted CL label — **ACCEPTED, added**

`443f7fb8-2a27-47c3-98f6-6a603c7a294e` — `putative_CL_label`, 47 values:
`serous secreting cell`, `mast cell`, `alveolar macrophage`, `basal cell`.

The authors' own CL assertion, distinct from the portal's `cell_type_ontology_term_id`.
The picker's rules name this case explicitly, so rule and sheet currently disagree and
one of them is wrong.

**Accepted.** Added; that dataset now scores 1.00. The picker's rule and the gold set
agree again, which is the outcome that matters here — they were contradicting each
other.

### 2.3 A coarse transcriptomic family — **DECLINED**

`bc474348-6dbd-483a-acb7-f295d1521fa2` — `RNA family`, 9 values: `ET`, `IT`, `Pvalb`,
`Vip`, `Lamp5`.

Standard cortical cell classes, sitting one level above the curated
`BICCN_subclass_label`.

**Suggested:** add.

### 2.4 A compartment column — **DECLINED**

`db34a663-a726-4404-9b50-bad19c607d0b` — `compartment`, 4 values: `stroma`,
`endothelium`, `fetal_nephron`.

Broad lineage, varying per cell. Curated instead is `cell_state`, which has 2 values and
is `na` for almost every cell — the less useful of the two is the one listed.

**Declined** on review: `compartment` is not added and `cell_state` stays. `db34a663`
therefore remains at Jaccard 0.33 — the picker picks `compartment` (which rule 5 tells it
to, being a varying lineage column) and skips `cell_state`. A known disagreement, not an
open defect.

---

## 3. Policy questions

These are the cases where the picker and the curators disagree *consistently*, which
suggests a rule that has never been written down rather than a mistake on either side.
A decision on each would settle several datasets at once.

### 3.1 Composite labels — cell type concatenated with something else

`ac818189`: `cell_type_source` (72) `NK_COVID_SEV`, `T_COVID_LDN`; `cluster_source`
(2224) `NK.CD16hi.1_COVID_SEV`; `major_subset_source`, `minor_subset_source`.
`5b8941a9`: `Organ_cell_lineage` (172) `Eye-Retinal progenitors and Muller glia`,
`Adrenal-Adrenocortical cells`.

Curation includes these. The picker rejects them as composites — a cell type crossed
with a disease cohort or an organ, so the value is not a cell-type name and the
cardinality is inflated by the other factor.

**Question:** are composites in scope? If yes, the picker's rules need to say so. If no,
five curated entries should come out.

### 3.2 Predicted and transferred labels

`b13072bd`: `scanvi_label` (29, includes `unlabeled`), `transf_ann_level_1_label` …
`transf_ann_level_5_label`.
`5b8941a9`: `Matched_BCA_cell_name` (44, mostly `nan`), `Matched_MCA_cell_name` (190).

These are model predictions or cross-atlas matches, not assertions the authors made
about their own cells. Curation includes the `Matched_*` pair; nothing says whether
`scanvi_label` or `transf_*` are in or out.

**Question:** a distinct `Content` value — "predicted cell type" — would separate these
cleanly and let evaluations opt in or out. Worth adding?

### 3.3 A cell-type column with an anatomical name

`ac818189`: `GEX_region`, 6 values: `B: TEM/prolif. T/NK cells`,
`A: CD4/naive/reg. T cells`.

Curated, and correctly so — the values are cell types. But the *name* says region, and
the picker skipped it on that basis. Noted here only as evidence that the values, not
the name, have to be read. No change needed.

### 3.4 Sub-clusters in a single-population dataset

`fb995261-472e-4ebc-99b0-d1136e1fad8a` — a platelet dataset. `Cell.class`, `Cell.group`
and `Lineage` are all constant, and curation records no cell-type field, correctly.
But `sub_cluster` has 6 values, `plt_0` … `plt_4`, varying per cell.

**Question:** is an unnamed sub-cluster within one population a cell-type annotation?
It is the only per-cell structure in the dataset. Currently the picker says yes and
curation says nothing at all.

---

## 4. Two places the picker is wrong, recorded for completeness

Not curation issues — listed so this document is a full account of the 11 disagreements.

- `bea5aacc-7625-4d7c-a3bd-88f9f9cdcec2`: picked `Cluster`, 17 string-encoded integers
  (`'6'`, `'0'`, `'2'`). A cluster index. The picker's own rule 3 forbids this and it
  broke it.
- `f202ae56-b9b6-48bd-87cd-fda4561d9dc9`: picked `structure` — `proximal tubules`,
  `Distal tubules`. Anatomy, not cell type.

---

## 5. Where this leaves the numbers

Sections 1, 2.1 and 2.2 are applied: **Jaccard 0.940, precision 0.958**, up from 0.926
and 0.944, with the picker unchanged. Ten datasets still disagree with curation:

| dataset | J | why it still disagrees |
|---|---|---|
| `fb995261` | 0.00 | §3.4 open — sub-clusters in a single-population dataset |
| `db34a663` | 0.33 | §2.4 declined — known disagreement |
| `5b8941a9` | 0.40 | §3.1 and §3.2 open — composites and matched labels |
| `ac818189` | 0.44 | §3.1 open — composite `*_source` columns |
| `bea5aacc` | 0.50 | **picker error** (§4) — numeric cluster index |
| `bc474348` | 0.67 | §2.3 declined — known disagreement |
| `b13072bd` | 0.68 | §3.2 open — `scanvi_label`, `transf_ann_level_*` |
| `18fb432a` | 0.80 | `dev_state`, unreviewed |
| `f202ae56` | 0.83 | **picker error** (§4) — anatomical `structure` |
| `b351804c` | 0.93 | §3.2 open — `scanvi_label` |

So of the ten, two are picker errors, two are accepted disagreements, five hang on the
open policy questions in section 3, and one (`dev_state`) has not been reviewed. Settling
section 3 would resolve five of them at once, in one direction or the other.

The two errors in section 4 are genuine and will be addressed in the picker's rules
separately.
