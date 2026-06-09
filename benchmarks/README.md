# ClangQuill vs Doxygen benchmarks

A standard-library-only harness that times **ClangQuill** against **Doxygen** on
real C++ codebases, with each tool's two pipeline stages measured separately.

| Stage | ClangQuill | Doxygen |
|-------|------------|---------|
| parse → structured intermediate | `clangquill build` (C++ → MyST Markdown) | `doxygen` with `GENERATE_XML` |
| render → human-facing HTML | `sphinx-build` (MyST → HTML) | `doxygen` with `GENERATE_HTML` |

The "full HTML" cost is `clangquill-myst + clangquill-sphinx` versus
`doxygen-html`, reported next to the per-stage numbers and the parse-only
comparison (`clangquill-myst` vs `doxygen-xml`).

## Scenarios

For every `(repo, stage)` pair, three scenarios are timed:

- **cold** — build from a clean state (a fresh clangquill `--cache-dir`).
- **noop** — immediately rebuild with no source change.
- **incremental** — apply a small fixed patch, then rebuild.

ClangQuill's incremental cache (only active with `--cache-dir`) makes *noop* and
*incremental* cheap — it skips the parse and rewrites only changed pages. Doxygen
has no parse cache and re-parses on every run, which is exactly the contrast the
benchmark surfaces.

## Prerequisites

`benchmarks/` is a self-contained [uv](https://docs.astral.sh/uv/) project
(`pyproject.toml` + `uv.lock`). Its dependencies are the tools the harness
*drives* — the **published `clangquill` binary wheel** (which bundles libclang,
so there is no C++ build), plus `sphinx` and `myst-parser` for the render stage:

```bash
# From the repo root: install the locked toolchain into benchmarks/.venv
uv sync --frozen --project benchmarks
# doxygen is a system package, not a Python dependency:
sudo apt-get install doxygen   # or your platform's equivalent
```

The harness itself (`benchmark.py`) is standard-library only. Any tool that is
missing is **skipped with a warning** rather than failing the run, so you can
benchmark a subset (e.g. only the ClangQuill stages).

## Usage

Run through `uv` so the locked `clangquill`/`sphinx-build` are on `PATH`:

```bash
# Full comparison across every config in configs/
uv run --project benchmarks python benchmarks/benchmark.py

# Fast smoke test: this repo, parse stage only, one repetition
uv run --project benchmarks python benchmarks/benchmark.py \
    --repos clangquill --tools clangquill-myst --repeat 1 --warmup 0

# All four stages on one repo
uv run --project benchmarks python benchmarks/benchmark.py --repos clangquill \
    --tools clangquill-myst,clangquill-sphinx,doxygen-xml,doxygen-html
```

(If you already have `clangquill`/`sphinx-build`/`doxygen` on `PATH`, you can
drop the `uv run --project benchmarks` prefix and just run
`python benchmarks/benchmark.py`.)

Key flags (see `--help` for all): `--repos`, `--tools`, `--scenarios`,
`--repeat`, `--warmup`, `--work-dir`, `--results-dir`, `--fresh-clone`, and
`--clangquill/--sphinx/--doxygen` to override the tool commands.

## Output

Each run writes a timestamped pair into `benchmarks/results/` (gitignored):

- `<ts>.json` — full structured data: environment + tool/libclang versions,
  resolved git commit per repo, and per repo/stage/scenario samples (wall, CPU,
  peak RSS, exit code) plus work metrics (clangquill symbol/file/page counts and
  on-disk output file count + bytes for both tools).
- `<ts>.md` — a readable table per repo (median wall-clock seconds) with the
  derived full-HTML / parse comparisons and cache speedups; also echoed to stdout.

## Continuous benchmarking

The `benchmark` GitHub Actions workflow (`.github/workflows/benchmark.yml`) runs
on push to `main`, on a weekly schedule, and on manual dispatch. It installs the
locked toolchain, runs the harness, appends the report to the job summary,
uploads the raw results as an artifact, and then regenerates
[`docs/benchmarks.md`](../docs/benchmarks.md) and opens a pull request against
`main` with the refreshed numbers (so the published docs always show the latest
results). By default it benchmarks every config under `configs/` (the external
repos are cloned blobless); a manual dispatch can narrow `--repos` or change
`--tools` via the workflow inputs.

## Configs

One TOML file per target in `configs/` (`clangquill`, `dune-gdt`, `abseil`,
`eigen`). Schema:

```toml
name = "eigen"
repo = "https://gitlab.com/libeigen/eigen.git"   # omit + local=true to use this repo's tree
ref  = "3.4.0"                                    # pinned tag/commit (fallback to default branch)
local = false
std = "c++17"
include_dirs = ["."]            # -I dirs for clangquill, relative to repo root
defines = []                    # -D defines
compile_args = []               # extra clang args
inputs = ["Eigen/src/Core/*.h"] # clangquill globs (relative to repo root)
doxygen_input = ["Eigen/src/Core"]  # Doxygen INPUT dirs (RECURSIVE=YES), same coverage
[patch]
files = ["Eigen/src/Core/Matrix.h"]  # deterministic incremental-edit targets
```

The "fixed patch" is a constant, documented C++ snippet appended to each
`patch.files` target (identical across repos) and reverted with `git checkout`
after each measured run. Pinning `ref` guarantees the file exists, making the
edit deterministic without shipping brittle diffs.

## Benchmarking practices baked in

- **Pinned refs** per repo for reproducibility (with a recorded fallback to the
  default branch if a pinned ref is missing).
- **Warmup + repetitions**: `--warmup` un-recorded passes prime the OS page
  cache / git / disk; `--repeat` recorded passes are aggregated to
  min/median/mean/stddev, with the **median** as the headline.
- **Per-process metrics** via `os.wait4`: CPU user+sys time and peak RSS, not
  wall clock alone, so scheduler noise is visible.
- **Fair inputs**: both tools are pointed at the same files; outputs go to
  isolated directories reset between repetitions; tools run quietly with logs
  captured under `.work/_bench/<repo>/logs/`.
- **Single-threaded & graphviz-free**: Doxygen runs with `HAVE_DOT = NO` and
  ClangQuill is single-threaded, so neither gets a parallelism advantage.
- **Recorded provenance**: tool + libclang versions, resolved commit, machine
  info and timestamp are stored with the numbers.

### Caveats

- **abseil / eigen / dune-gdt** are template- and dependency-heavy. Without their
  full include trees, libclang emits diagnostics and may extract fewer symbols
  than Doxygen's tolerant, non-compiling lexer. The harness records this (exit
  codes, symbol counts) and does **not** treat it as a failure. Extend each
  config's `include_dirs` if you have the dependencies available.
- Things this headless harness cannot control are left to the operator: pin the
  CPU governor to `performance`, run on an otherwise-idle, thermally-stable
  machine, and prefer more `--repeat` passes for stable medians.
