# paper-access: repo-side evals

What is here measures the **supplement manifest check**, the logic behind the
`retrieve-supplements` hook (`plugins/paper-access/hooks/check_supplements.py`).
The shipped smoke cases for the plugin are in `plugins/paper-access/evals/`.

## `manifest_catch_rate.py` — how much of what goes wrong does the check catch

```sh
packages/paper-access/.venv/bin/python evals/paper-access/manifest_catch_rate.py          # markdown table
packages/paper-access/.venv/bin/python evals/paper-access/manifest_catch_rate.py --json   # JSON
```

Deterministic, offline, free. It builds a clean store in a temp directory from
the package's own record and supplement types (two present files with digests,
an archive with an extracted member, a skipped figure, a deferred file with
`bytes_transferred` and a gap, a missing file with a gap, a listed file), checks
that it passes `supplements check` clean, then applies one mutation at a time to
every entry it fits and records whether the check (`record.check` plus
`check_on_disk`) flags it.

The errors are synthetic: the rates measure the check against these mutations,
not how often a real fetch goes wrong in each way.

`caption_swapped` is a control. Swapping two files' descriptions leaves both real
and sourced, so only someone who opens the files can tell. The check is not meant
to catch it, and the expected rate is 0%. That kind of error needs judgement and
is outside what a hook can do.

`test_manifest_catch_rate.py` pins every class except the control at 100% and the
control at 0%. It needs `paper_access` importable, so it runs under the
paper-access venv (`./dev.sh` does this) and skips elsewhere.
