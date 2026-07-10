# Publishing

`new-feature` publishes through PyPI Trusted Publishing from GitHub Actions.

## One-Time PyPI Setup

Create a pending publisher at <https://pypi.org/manage/account/publishing/>.

Use these values:

- PyPI project name: `new-feature`
- Owner: `crypdick`
- Repository name: `new-feature`
- Workflow name: `publish.yml`
- Environment name: `pypi`

## Release

1. Push the release workflow to GitHub.
2. On GitHub, create an environment named `pypi`.
3. Publish a GitHub release for the version in `pyproject.toml`.

The `Publish to PyPI` workflow builds the source distribution and wheel, then uploads them without storing a PyPI API token in GitHub secrets.

## Local Verification

Build and validate the distributions before cutting a release:

```bash
uv build
uvx twine check dist/new_feature-0.1.0.tar.gz dist/new_feature-0.1.0-py3-none-any.whl
uv run --isolated --with dist/new_feature-0.1.0-py3-none-any.whl new-feature --help
```

For a manual local upload, pass exact artifact filenames instead of `dist/*`:

```bash
uv publish dist/new_feature-0.1.0.tar.gz dist/new_feature-0.1.0-py3-none-any.whl
```
