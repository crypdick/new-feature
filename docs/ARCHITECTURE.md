# Architecture

The Python package lives in `src/new_feature/`. Start with these modules:

- `app.py` and `cli_parser.py`: entry point, signals, and argument parsing.
- `cli.py`: lifecycle dispatch and merge workflows.
- `creation.py`: creation, inert branch import, explicit bootstrap, and creation JSON.
- `navigation.py` and `changes.py`: path lookup, shell completion, and guarded change snapshots.
- `prune.py`: batch cleanup through the normal teardown lifecycle.
- `output.py`: stdout isolation for machine-readable mutation results.
- `inspection.py`: human and versioned JSON inspection and repair reports.
- `teardown.py` and `processes.py`: teardown preview and Linux process protection.
- `untracked.py`: local file transfer, disposable patterns, and preservation checks.
- `config.py` and `allocator.py`: configuration and environment allocation.
- `manifest.py`: feature records and locks.
- `git.py`, `commands.py`, and `execution.py`: Git, shell commands, and feature execution.
- `control_checkout.py`: verified ownership lookup across registered Git worktrees.
- `feature_state.py` and `recovery.py`: inspection and repair.
- `agent.py`: agent selection, prompts, and launch.
- `hook_policy.py`, `shell_commands.py`, `rule_checker.py`, and `hook_install.py`: worktree policy,
  neutral i-insist checker, and rule installation for new-feature.

Each original checkout owns its manifest. Creation records durable `initializing`
intent before creating Git resources, then `active` after setup succeeds. Existing
paths or owned-branch name collisions are refused before recording intent.
Inspection reports unfinished creation or setup as `setup-incomplete`.
Existing-branch imports instead record `inert` until explicit bootstrap. Imports disable
checkout hooks, filters, and filesystem monitors; configured setup and agents stay stopped.
Failed bootstrap preserves the imported checkout for inspection and retry. The manifest
records branch ownership separately: teardown and repair retain attached existing local
branches, while branches created by the tool remain eligible for deletion.
If Git resource creation fails, the intent remains inspectable. Doctor removes intent
with no resources and missing-worktree imports without deleting their existing branches,
even when those branches are unmerged. Interrupted creation with surviving resources
requires inspection and normal teardown protections.

Manifest parsing checks canonical slug/key relationships, unique branch and resolved
worktree claims, and relative worktree paths contained within the control checkout.
Lifecycle operations verify recorded paths and branches against Git's registered
worktree inventory. Inspection reports mismatches as `worktree-error`; reopening,
execution, merge, and teardown refuse them, including forced teardown.

Each new feature receives a persisted generation token. Change inspection holds the same
shared execution lock as `exec`, verifies the manifest and checkout identity before and
after reading Git status, and rejects stale expected generations. Legacy records have no
token; their JSON generation is null. This coordinates lifecycle operations without
claiming an atomic snapshot against manual file edits. Batch pruning revalidates each
feature under its operation lock and uses normal teardown; previews acquire no locks.
Lifecycle commands resolve the current checkout through Git's worktree inventory and
matching manifest paths and branches. One matching owner selects that checkout;
multiple owners or a branch mismatch fail. Unreadable manifests fail for the current
checkout and ancestors containing it under `.worktrees`; unrelated siblings are skipped.
Unmanaged linked worktrees keep their own state. No owner is inferred from the common
Git directory. The raw Git root resolver used by guards stays checkout-local.

Create, merge, teardown, and repair share a per-feature lock. Manifest updates use a
separate lock. Pre-merge checks can run concurrently for different features, but a
target merge lock serializes checkout changes. On POSIX, `exec` holds a shared `flock`
on the same inode as the exclusive FileLock lifecycle lock. Concurrent commands can
run, while feature mutations fail fast until all commands exit. Command failure and
cancellation release the lock. Commands own a process group for cancellation cleanup.
Teardown preview takes no locks and mutates no state; its snapshot can change before
a real teardown.

Merge selects the target checkout before capturing the revision for rollback. Failures
during merge, post-merge checks, commit, or bookkeeping trigger restoration only when
HEAD, branch, MERGE_HEAD, index tree, tracked working-tree diff, untracked paths, and
the feature tip still match the last tool-owned state. Uncertain ownership preserves
the checkout for manual recovery; no blanket `git clean` runs. Post-merge checks
may finish the exact prepared merge (same ordered parents and tree); unrelated
commits or edits detected at these boundaries are never adopted. The target lock
serializes cooperating `new-feature` operations; it cannot lock out manual Git or
file edits between verification and a subsequent Git command. Keep external
writers out of the target checkout during merge. `merge --ignore-dirty` first refuses
when uncommitted paths overlap the paths between HEAD and the `git merge-tree` result,
so the later restore cannot conflict with the merge itself; it then stashes
uncommitted target changes inside the target lock, before ownership is captured,
so rollback and ownership checks see the same clean checkout as a normal merge;
the stash is applied and dropped by commit afterwards, on success or failure. Push happens
outside that scope, so push failure retains the local merge.

Merge ownership records initialized submodule HEADs, branches and dirty status
separately from the parent's tracked working-tree diff. An unchanged clean
submodule checkout may still point at the old commit after Git stages a new
gitlink. Post-merge checks may reconcile that checkout to exactly the indexed
commit, retaining its branch or detaching HEAD. Other commits, branches, dirty
files and initialization changes remain interference. No automatic submodule
reset or update is performed. If a failing check has changed a submodule checkout,
the merge is preserved for manual recovery rather than rolling back across that
checkout change.

Git ancestry determines integration. The manifest's `merged` status doesn't hide later
commits. Teardown and repair also accept patch-equivalent branches, excluding unmerged
merge commits whose conflict resolutions patch comparison can't represent.

Inspection reports unreadable worktrees as `worktree-error` and leaves them untouched.
`list` still succeeds, while `doctor` exits nonzero. JSON inspection and teardown
preview contracts are documented in the [README](index.md#lifecycle).

Git commands, lifecycle commands, and agents ignore inherited Git repository-location
overrides. Their working directory selects the repository. Transport, authentication,
and explicitly configured lifecycle environment values remain available.

## Local files

Local files stay outside Git's merge transaction. `merge --include-untracked`
validates destination conflicts before the Git merge, then makes atomic copies
without overwriting after the commit succeeds. Originals remain until teardown;
partial transfer can be retried against identical completed copies. A transfer
failure does not roll back the completed Git merge. Normal teardown checks tracked
changes, branch integration, processes, and preservation of non-disposable local
files before requesting forced Git worktree removal. Preservation is rechecked
after cleanup; this prevents Git's disregard for ignored files from losing work.
Checkout identity and branch integration are also rechecked after configured cleanup:
cleanup-created commits must not be discarded by ordinary teardown. Worktree removal
force and branch deletion force are separate Git-helper choices. After proving integration
against the configured target, teardown may force branch deletion because Git's own
`branch -d` checks a possibly stale upstream and cannot recognize patch-equivalent work.
See [Local file transfer](https://new-feature.ricardodecal.com/#local-file-transfer) for policy and exclusions.

## Agent guards

Guards enforce these policies through i-insist:

- Create and remove worktrees through `new-feature`. This also blocks Claude Code's
  `EnterWorktree` when it creates a worktree and Agent calls with worktree isolation.
  `EnterWorktree` with a `path` can still enter an existing worktree.
- Edit on a feature branch, except before the first commit or when editing
  ignored, untracked paths. Tracked files remain protected even under ignored
  directories. Content writes protect both the named entry and its resolved destination,
  including symlinks from a feature checkout into the target checkout. Removal, rename,
  link replacement and in-place editors protect the directory entry instead; removing
  a feature checkout's symlink does not write its target. Utilities still follow
  symlinks used as directory destinations unless their no-directory options apply,
  and `sed --follow-symlinks` explicitly protects the content destination.
- Merge into the target branch through `new-feature merge`. Merges on feature
  branches, `--continue`, `--abort`, `--quit`, help, and `git commit` remain allowed.
- Arguments after the feature name pass through to `git merge`; supplying them skips
  the default conflict preflight so Git's merge strategy options can take effect.

Edit checks also cover common shell writes: output redirections, `tee`, in-place
`sed` and `perl`, `cp`, `install`, `ln`, `mv`, `rm`, `touch`, and `truncate`.
Guards recognize Git directory options, literal `cd` commands, subshell scopes and
AND/OR lists, preserving shell's logical symlink-parent semantics. Leading assignments
and current-shell `command`/`builtin` prefixes are recognized; external `env` and
`sudo` invocations do not move the parent shell. Directory inference considers both
outcomes of a command; a failed `cd` never moves the inferred directory.
`CDPATH`/`PWD` overrides, relative `cd` with inherited `CDPATH`, dynamic `cd`, shell
control flow, process substitution (`<(` and `>(`), and `cd` combined with pipelines
or background commands fail explicitly instead of guessing a checkout. Use separate
simple commands and explicit input or output files in these cases.
Guards don't parse arbitrary scripts, interpreters such as `python -c`, Git aliases, or variable expansion.
Paths containing dollar signs are deferred to the post-command check rather than
treated as literal paths in the current checkout. This lets commands copy changes
into a worktree through `$W` and then run `git restore` in the target checkout.
Quoting is removed during parsing, so literal dollar signs are deferred too.
Heredoc bodies are input data, so their text is excluded from command checks.
Quoted delimiters, multiple heredocs, and `<<-` tab stripping are recognized;
redirections on the header and commands after the closing delimiter remain checked.
Command substitutions inside expanding heredocs fall under the post-command check.
A post-command rule covers those: before each shell command on the target branch, the
edit check records tracked changes in each checkout's Git directory, covering the
current directory and literal `cd` targets, one record per harness `tool_use_id`.
Git diff content fingerprints include binary contents, file modes and symlink targets,
so timestamp-preserving copies are detected and timestamp-only touches are ignored.
After the command, any tracked file that is newly changed, changed again, or deleted is reported to the
agent. The command's effects remain. Snapshots can detect changes but cannot tell which
command made them. The report asks the agent to check `git status` and `git log` for a
completed merge or concurrent edits before restoring anything. Move only edits you made
directly to a feature worktree. If `HEAD` or `MERGE_HEAD` moves
between the record and the check, or `new-feature` holds the target merge lock, only
unstaged changes count. This keeps a concurrent `new-feature merge`, which stages its
changes before committing them, from being reported as the command's edit. Edits that
are staged during that window aren't reported. Without a `tool_use_id`, calls share
one record, so one command can mask another's changes. Records older than a day are
pruned. Claude's failed tool calls are covered too. These checks require i-insist 0.6.0
or later.

Installation sets up i-insist from PyPI, verifies enabled hooks, and atomically
replaces the generated rule registration for new-feature. Checkers return JSON `null` to allow
an action or a nonempty denial message to block it. Evaluation errors exit nonzero
so i-insist blocks the action and reports stderr. The i-insist runner handles human
approval through `I insist` in the most recent human message.

The generated module reference describes internals. It doesn't define a stable
external Python API.
See [Contributing](CONTRIBUTING.md) for development and [Quality](QUALITY.md) for checks.
