# Design conventions

## Composition over inheritance

Combine small functions and plain objects directly. Add inheritance only when there is a real substitutability relationship, not to share incidental code.

## Parse, don't validate

Turn untrusted or unstructured inputs into typed values at the boundary. Downstream code should accept the parsed shape instead of repeatedly checking raw primitives.

## Semantic types

When a primitive starts carrying domain meaning, give it a name with `typing.NewType` or a focused type alias. Avoid passing anonymous `str`, `int`, or `dict` values through domain code once the concept matters.

## Code and docs stay coupled

When you document a value or invariant in prose, leave a short `NOTE:` at the code site that points back to the document. Update both in the same change.
