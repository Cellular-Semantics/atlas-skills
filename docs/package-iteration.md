# Iterating on a package while a skill uses it

How to change `packages/<x>` without a release for every edit, and how to
release once the behaviour settles. Companion to "Making a change" in the
README.

The `--from` pin in SKILL.md is the only thing that selects a package version.
`plugin.json`'s version selects which copy of the *plugin* an installed user
has: Claude Code refreshes an installed plugin only when that string changes.
So bumping the plugin does not pull new package code, but not bumping it means
nobody already installed receives the new pin.

Three loops, in increasing cost:

**Skill text or an advice document.** Load the plugin from your worktree for
one session, no install needed:

```
claude --plugin-dir plugins/onto-mapping
```

A project using a `directory` marketplace also picks up edits next session.
Bump `plugin.json` when you open the PR; `version-bumps` will insist.

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

**Releasing.** Once the behaviour has settled: bump the package's
`pyproject.toml` (and `__version__`, where it is a literal), move the pin in
every skill that uses it, bump those plugins' versions, and regenerate
`docs/pins.md`. One PR or two, as suits. On merge `release` tags the package,
then the plugin — never tag by hand. Then drop `OQ_BIN` from the consuming
project so it runs the release.

A pin must resolve for someone with a cold cache. Check it the way CI does:

```
uvx --no-cache --from "git+https://github.com/Cellular-Semantics/atlas-skills@<tag>#subdirectory=packages/<dir>" "$(python3 scripts/versions.py cli <dir>)" --version
```

`scripts/versions.py cli` prints the package's console script, preferring the
one named after the directory: `onto-query` installs both `onto-query` and the
short `oq` the skill types.

### Quoting

Skills must write the full quoted command, or a shell function, not
`CMD="uvx …"` then `$CMD`. Unquoted parameters do not word-split under zsh, the
macOS default shell, so the variable form fails with
`command not found: uvx --from …`.
