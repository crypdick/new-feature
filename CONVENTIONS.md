# Design conventions

The `coding-conventions` skill shipped with Strictify provides advisory guidance.
Project-specific conventions below take precedence.

## Composition over inheritance

Prefer small functions and plain objects. Use inheritance for substitutability,
not incidental code reuse.

## Parse, don't validate

Parse untrusted or unstructured inputs into typed values at boundaries so
downstream code can rely on them.

## Semantic types

Use `typing.NewType` or focused type aliases when domain names clarify contracts
or help prevent mix-ups. Plain primitives are fine when their meaning is clear.

## Code and docs stay coupled

Update docs alongside behavior changes. Add a short `NOTE:` linking code to docs
when it helps keep a non-obvious value or invariant in sync.
