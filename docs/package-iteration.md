# Iterating on a package while a skill uses it

How to change `packages/<x>` without a pushed tag for every edit, and what
to do when the behaviour settles. Companion to the repo-level versioning
rules in CLAUDE.md.


The tag lives in the skill text, not in the plugin version. `plugin.json`'s
version is metadata — nothing resolves against it — so bumping it does **not**
pull new package code. The `--from` pin in SKILL.md is the only thing that
selects a package version.

Which gives three loops, in increasing cost:

**Skill text or an advice document.** Edit it in the worktree. A project using
a `directory` marketplace picks it up next session: no version bump, no
reinstall, no tag. Bump `plugin.json` when you commit, per CLAUDE.md, but that
is bookkeeping rather than a mechanism.

**Package code, while the behaviour is still moving.** Set `OQ_BIN` (or the
equivalent for that package) to an editable install and call the binary
directly:

```
uv venv && uv pip install -e "packages/onto-query[test]"
# then in the consuming project's .claude/settings.json:
#   "env": { "OQ_BIN": "/abs/path/to/.venv/bin/oq" }
```

Do **not** try to point the `--from` pin at a local directory instead. `uvx`
caches the build: editing the source and re-running gives the stale version
back, silently. Measured — a version bump in `__init__.py` was not picked up,
while the editable install reported it immediately.

**Releasing.** Once the behaviour has settled: bump the package version, tag
`pkg-<dir>--vX.Y.Z`, push the tag, update the pin in every skill that uses it,
and bump those plugins' versions — all in one commit, per CLAUDE.md's
same-change rule. Then drop `OQ_BIN` from the consuming project so it runs the
release.

A pin must resolve for someone with a cold cache. Check it the way CI does:

```
uvx --from "git+https://github.com/Cellular-Semantics/atlas-skills@<tag>#subdirectory=packages/<dir>" <dir> --version
```

Note the CLI name must match the package directory — that is what the check
invokes. `onto-query` carries a second console script for exactly this reason,
alongside the short `oq` the skill types.

### Quoting

Skills must write the full quoted command, not `CMD="uvx …"` then `$CMD`.
Unquoted parameters do not word-split under zsh, the macOS default shell, so
the variable form fails with `command not found: uvx --from …`.
