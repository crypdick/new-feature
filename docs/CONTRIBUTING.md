# Contributing

## Releases

Use `uv version --bump patch` to update the package version. Merging the version change to
`main` publishes the distributions to PyPI, tags the merged commit as `v<VERSION>`, and creates
a GitHub Release.

The release workflow can also run manually to recover from a partial release.
