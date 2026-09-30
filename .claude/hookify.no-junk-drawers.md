---
name: no-junk-drawers
enabled: true
event: file
conditions:
  - field: file_path
    operator: regex_match
    pattern: (utils|helpers|misc|common|shared|general)\.py$
action: warn
---

You're creating or editing a module with a generic name. Follow the principle
"treat directory structure and filenames as an interface": give every file a clear,
domain-specific purpose.

Instead of `utils.py`, name the module after what it actually does:

- `billing/compute.py` not `billing/utils.py`
- `auth/tokens.py` not `auth/helpers.py`
- `parsing/csv_reader.py` not `common/misc.py`

Give shared code a specific name. If you need a shared utility, name it after what
it does and put it where it belongs. Prefer a shared package with a clear name and
centralized invariants over custom helpers scattered across domains. If only one
module uses the functions, keep them in that module.
