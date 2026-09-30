---
name: taste-enforcer
enabled: true
event: prompt
pattern: don.?t use|always prefer|avoid|never do|instead of|I hate when|stop using|should always|should never|prefer .+ over|ban |forbid
action: warn
---

A keyword matched. The user might have expressed a coding preference.

When the user expresses a code preference that requires ongoing enforcement,
determine which mechanism can enforce it:

1. **A prek hook script:** For code patterns that static analysis can detect, create
   or update a script in `scripts/prek_hooks/` and register it in `prek.toml`.
   Examples include avoiding bare `except` clauses and `print` statements.

2. **A hookify rule:** For Claude's behavior during sessions, create a
   `.claude/hookify.{name}.md` rule. Replace `{name}` with a descriptive rule name.
   Examples include avoiding `utils.py` files and using `NewType` for identifiers.

3. **A `pyproject.toml` setting:** For preferences that map to an existing tool's
   configuration, update that configuration. For example, use a Ruff rule to ban
   star imports.

If a hook or rule already enforces the preference but the user still had to mention
it, investigate why enforcement failed. Check for a narrow pattern, an incorrect
event type, or a missing edge case, then propose a fix to strengthen the hook or rule.

If the user previously expressed a preference in this conversation that this hook
missed, write a hook for that preference too.
