# annotation-hierarchy

`celltype.l1`, `celltype.l2` and `celltype.l3` — a three-level author hierarchy, all
three curated. No traps: no constant columns dressed as cell types, no numeric cluster
ids in the running.

A good answer names all three, gives the distinct-label count at each level, and shows
how they nest. Naming only `celltype.l3` is a partial answer: the user asked about
granularity.

This is the control case. If it fails, look at the plumbing — the CLI, the sub-agent
dispatch, the profile — before looking at the picking rules.

Measured 2026-09-28: 161,764 cells x 35 obs columns.
