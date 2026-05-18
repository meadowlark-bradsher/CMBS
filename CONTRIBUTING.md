# Contributing to CMBS

Thanks for your interest in CMBS. This document covers the basics; for the
"why" of the project, see [docs/architecture.md](docs/architecture.md).

## Reporting bugs and proposing features

Open an issue on [github.com/meadowlark-bradsher/CMBS/issues](https://github.com/meadowlark-bradsher/CMBS/issues).
Bug reports should include the smallest reproducer that exhibits the problem;
feature proposals should describe the use case before the implementation.

For sensitive reports (security, conduct), see [SECURITY](#security) and the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

```bash
git clone https://github.com/meadowlark-bradsher/CMBS.git
cd CMBS
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

This installs the package in editable mode plus the `dev` extra (currently
just `pytest`).

## Running checks locally

```bash
pytest -q          # full test suite (~0.3s)
ruff check .       # lint
mkdocs build --strict  # docs build (requires `pip install mkdocs`)
```

CI runs the same on Python 3.10, 3.11, and 3.12 — see
[.github/workflows/tests.yml](.github/workflows/tests.yml).

## Pull request workflow

1. **Open an issue first** for non-trivial changes so we can agree on scope
   before code gets written. Drive-by docs fixes don't need this.
2. **Branch from `main`.** Branch names like `fix/...`, `feat/...`,
   `docs/...`, `chore/...` are appreciated.
3. **Keep commits focused.** Conventional Commits style (`type: short
   summary`) is used in this repo's history — mirroring it makes the log
   easier to skim.
4. **Add tests** for behavior changes. The existing test suite is in
   `tests/`; the kernel's invariant tests in `tests/test_v0_core.py` are
   the authoritative reference for kernel semantics.
5. **Update docs** when public surface or use cases change. The
   `docs/reference/` tree must stay accurate; `docs/use-cases.md` is the
   place for new patterns.
6. **CI must pass** before merge.

## Code style

- Python 3.10+ (the `pyproject.toml` floor)
- Type hints everywhere on public surface
- `ruff check .` clean — see `[tool.ruff]` in `pyproject.toml` for the
  enabled rule set
- Docstrings on public classes and methods; one-liners are fine if the
  signature carries the meaning
- Don't add comments that restate the code — comments should explain
  *why*, not *what*

## What lives where

- **Kernel** (`cmbs/core.py`): invariant enforcement only. Changes here
  need careful review against `tests/test_v0_core.py`.
- **Servers** (`cmbs/belief_server.py`, `cmbs/oplog_server.py`): session
  management, audit, policy enforcement above the kernel.
- **SPI** (`cmbs/spi/`): protocols third parties implement against. Treat
  signatures as semi-stable; breaking changes need a migration note.
- **Adapters** (`cmbs/adapters/`): domain translation. Each adapter is
  self-contained. New adapters welcome — follow the
  `twenty_questions/` and `itbench/` shape.

## Security

For potential security issues, open a private vulnerability report via
[GitHub Security Advisories](https://github.com/meadowlark-bradsher/CMBS/security/advisories/new)
rather than a public issue.

## License

By contributing, you agree your contributions will be licensed under the
[Apache License 2.0](LICENSE).
