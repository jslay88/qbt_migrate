# Contributing

## Setup

```
python -m venv venv
. venv/bin/activate
pip install -e '.[dev]'
pre-commit install
```

`.tool-versions` pins the Python used for development if you use asdf.

## Checks

Everything CI runs is available through tox:

```
tox -e lint        # ruff check, ruff format --check, mypy, bandit
tox -e unittest    # pytest under coverage
tox -e coverage    # coverage report plus diff-cover against the base branch
tox -e build       # PEP 517 build and twine check --strict
tox                # lint plus the full 3.10 to 3.14 matrix
```

`pre-commit run --all-files` covers the same lint surface plus actionlint on the
workflows.

## Expectations

* Branch coverage is enforced at 100% for the package, and `diff-cover` requires
  100% on changed lines. New behavior needs a test.
* mypy runs `strict = true` over `qbt_migrate`. Tests are not type checked.
* Formatting is `ruff format`, 79 columns. No black, no isort.
* Supported Python is 3.10 and up. Do not add compatibility shims for older
  versions.

## Fixture files

`tests/test_files/*.fastresume` are real bencoded files. Prefer the
`write_fastresume` fixture over adding new ones when the point of the test is
the exact contents of the keys, since a dict in the test is readable and a
binary blob is not.

Tests must never open the checked-in fixtures directly. Use `fastresume_path`
or `copy_fastresume`, which copy into a temp directory first.

## A note on paths

If you are touching path matching, read [docs/paths.md](docs/paths.md) first.
The separator and trailing slash rules are subtle and are the source of most
bug reports.
