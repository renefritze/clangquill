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

ClangQuill's incremental cache (only active with `--cache-dir`) makes *noop*
cheap — the parse is skipped entirely. *incremental* re-parses only the
translation units whose include closure contains the patched file and rewrites
only the changed pages. Note the configured patch targets are widely-included
headers, so the stale set can legitimately approach the whole module. Doxygen
has no parse cache and re-parses on every run, which is exactly the contrast
the benchmark surfaces.

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
on version tags (`v*`) and on manual dispatch. It installs the locked
sphinx/myst toolchain, **builds clangquill from the checked-out source** (against
LLVM 22 from apt.llvm.org, the same libclang major the release wheels bundle) so
the published numbers measure the commit they are labeled with, runs the
harness, appends the report to the job summary, uploads the raw results
as an artifact, and — on a tagged run, or a manual dispatch with the
`publish_docs` input enabled — regenerates
[`docs/benchmarks.md`](../docs/benchmarks.md) and opens a pull request against
`main` with the refreshed numbers (so the published docs track tagged releases,
and can be refreshed from `main` between releases when the numbers have moved).
By default it benchmarks every config under `configs/` (the external repos are
cloned blobless); a manual dispatch can narrow `--repos` or change `--tools` via
the workflow inputs.

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
inputs = ["Eigen/src/Core/**/*.h"]  # clangquill globs (relative to repo root)
doxygen_input = ["Eigen/src/Core"]  # Doxygen INPUT dirs, same tree as the globs
doxygen_recursive = true            # Doxygen RECURSIVE; false when the glob is single-level
doxygen_file_patterns = ["*.h"]     # Doxygen FILE_PATTERNS; pin to the glob's extension
group_by = "namespace"              # clangquill --group-by (empty = tool default "symbol";
                                    # set "namespace" for namespace-rooted libraries so one
                                    # root namespace doesn't collapse onto a single huge page)
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
- **Fair inputs**: both tools are pointed at the same files — the clangquill
  globs and Doxygen's `RECURSIVE`/`FILE_PATTERNS` are kept in lockstep per
  config so neither tool processes files the other does not; outputs go to
  isolated directories reset between repetitions; tools run quietly with logs
  captured under `.work/_bench/<repo>/logs/`.
- **Work metrics in the report**: each repo section pairs the timings with the
  cold-run symbol/file/page counts and output sizes for both tools (plus any
  non-zero exit codes), so a fast run that extracted little is visible as such.
- **Crashed renders are not timings**: a non-zero `sphinx-build` exit means the
  build died partway, so its wall clock measures a fraction of the work. Those
  samples are kept in the raw JSON but excluded from the statistics, and the
  report cell shows `failed` instead of a number. (Parse-stage non-zero exits
  still record normally — there they signal diagnostics, not an aborted build.)
- **All cores for both tools & graphviz-free**: Doxygen runs with
  `NUM_PROC_THREADS = 0` (all available CPUs) and `HAVE_DOT = NO`, matching
  ClangQuill's default `jobs = 0` (auto-detected CPU count) parallel parse and
  `sphinx-build -j auto`, so neither tool gets a parallelism advantage.
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
