#!/usr/bin/env python3
"""Benchmark ClangQuill against Doxygen across real C++ codebases.

The harness times the two stages of each tool's pipeline separately so the
numbers line up apples-to-apples:

    stage              ClangQuill                       Doxygen
    -----------------  -------------------------------  ----------------------
    parse -> structured  ``clangquill build`` (-> MyST)   ``doxygen`` GENERATE_XML
    render -> HTML       ``sphinx-build`` (MyST -> HTML)   ``doxygen`` GENERATE_HTML

For every ``(repo, stage)`` pair three *scenarios* are measured, each repeated
``--repeat`` times after ``--warmup`` un-recorded passes:

    cold         build from a clean state (fresh clangquill ``--cache-dir``)
    noop         immediately rebuild with no source change
    incremental  apply a small fixed patch, then rebuild

ClangQuill's incremental cache (only active with ``--cache-dir``) makes the
``noop`` and ``incremental`` scenarios cheap; Doxygen has no parse cache and
re-parses every run, which is exactly the contrast the benchmark surfaces.

Design notes / benchmarking practices baked in:

* per-process CPU time and peak RSS are captured via :func:`os.wait4` (not just
  wall clock), so a noisy scheduler is visible in the data;
* git refs are pinned per repo for reproducibility (with a recorded fallback to
  the default branch if a pinned ref is missing);
* a warmup pass plus several repetitions are aggregated to min / median / mean /
  stddev, with the median reported as the headline figure;
* both tools are pointed at the same inputs, output to isolated directories that
  are reset between repetitions, and run quietly with logs captured to files;
* tool/toolchain versions, the resolved git commit, machine info and a
  timestamp are recorded alongside the numbers;
* a non-zero exit is recorded, not fatal: libclang emits diagnostics on heavy,
  dependency-rich repos (abseil/eigen) without their full include trees, and
  that is a real-world data point rather than a benchmark failure.

The driver depends only on the standard library; the tools it *drives*
(``clangquill``, ``sphinx-build`` + ``myst-parser``, ``doxygen``) are detected
at runtime and skipped with a warning when absent.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import shlex
import shutil
import statistics
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DEFAULT_CONFIG_DIR = HERE / "configs"
DEFAULT_WORK_DIR = HERE / ".work"
DEFAULT_RESULTS_DIR = HERE / "results"

# The four pipeline stages we know how to drive. ``clangquill-myst`` and
# ``doxygen-xml`` are the parse stages (structured intermediate); the other two
# are the human-facing HTML render stages.
ALL_STAGES = ("clangquill-myst", "clangquill-sphinx", "doxygen-xml", "doxygen-html")
ALL_SCENARIOS = ("cold", "noop", "incremental")

# A deterministic, identical-everywhere "fixed patch": a fully documented C++
# snippet appended to each configured target header. Appending (rather than
# shipping brittle unified diffs) is robust across pinned refs while still
# forcing a re-parse of exactly the touched file. The guard macro keeps repeated
# applications and odd include orders harmless.
PATCH_SNIPPET = """

#ifndef CLANGQUILL_BENCHMARK_PATCH_MARKER
#define CLANGQUILL_BENCHMARK_PATCH_MARKER
namespace clangquill_benchmark_patch {
/// A synthetic symbol injected by the ClangQuill benchmark harness to measure
/// incremental rebuild cost. It is reverted after every measured run.
///
/// \\param value an arbitrary input.
/// \\returns \\p value unchanged.
inline int benchmark_marker(int value) { return value; }
}  // namespace clangquill_benchmark_patch
#endif
"""


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
@dataclass
class RepoConfig:
    """One benchmark target, loaded from a TOML file in ``configs/``."""

    name: str
    repo: str = ""
    ref: str = ""
    local: bool = False
    std: str = "c++20"
    include_dirs: list[str] = field(default_factory=list)
    defines: list[str] = field(default_factory=list)
    compile_args: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    doxygen_input: list[str] = field(default_factory=list)
    patch_files: list[str] = field(default_factory=list)

    @classmethod
    def from_toml(cls, path: Path) -> RepoConfig:
        """Load a :class:`RepoConfig` from the TOML file at ``path``."""
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        patch = data.get("patch", {}) or {}
        return cls(
            name=data.get("name", path.stem),
            repo=data.get("repo", ""),
            ref=data.get("ref", ""),
            local=bool(data.get("local", False)),
            std=data.get("std", "c++20"),
            include_dirs=list(data.get("include_dirs", [])),
            defines=list(data.get("defines", [])),
            compile_args=list(data.get("compile_args", [])),
            inputs=list(data.get("inputs", [])),
            doxygen_input=list(data.get("doxygen_input", [])),
            patch_files=list(patch.get("files", [])),
        )


# --------------------------------------------------------------------------- #
# Measurement
# --------------------------------------------------------------------------- #
@dataclass
class Measurement:
    """The resource cost of a single subprocess run."""

    wall_s: float
    user_s: float
    sys_s: float
    maxrss_kb: int
    exit_code: int
    stdout: str

    def as_dict(self) -> dict:
        """Serialise the measurement to a JSON-friendly dict (RSS in MB)."""
        return {
            "wall_s": self.wall_s,
            "user_s": self.user_s,
            "sys_s": self.sys_s,
            "cpu_s": self.user_s + self.sys_s,
            "maxrss_mb": round(self.maxrss_kb / 1024, 1),
            "exit_code": self.exit_code,
        }


def measure(argv: list[str], cwd: Path, log_path: Path, env: dict | None = None) -> Measurement:
    """Run ``argv`` under ``cwd`` and capture wall time + per-process rusage.

    stdout/stderr are redirected to ``log_path`` (not a pipe) so there is no risk
    of a pipe-buffer deadlock and :func:`os.wait4` — not :meth:`Popen.communicate`
    — reaps the child, yielding the exact ``ru_utime``/``ru_stime``/``ru_maxrss``
    for *this* process. A non-zero exit is reported in the result, never raised.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    run_env = {**os.environ, **(env or {})}
    with log_path.open("wb") as log:
        start = time.perf_counter()
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdout=log,
            stderr=subprocess.STDOUT,
            env=run_env,
        )
        _pid, status, rusage = os.wait4(proc.pid, 0)
        wall = time.perf_counter() - start
    # Mark the Popen as reaped so its destructor does not warn or wait again.
    exit_code = os.waitstatus_to_exitcode(status)
    proc.returncode = exit_code
    return Measurement(
        wall_s=wall,
        user_s=rusage.ru_utime,
        sys_s=rusage.ru_stime,
        maxrss_kb=_maxrss_kb(rusage.ru_maxrss),
        exit_code=exit_code,
        stdout=log_path.read_text(encoding="utf-8", errors="replace"),
    )


def _maxrss_kb(ru_maxrss: int) -> int:
    """Normalize ``rusage.ru_maxrss`` to kilobytes.

    Linux reports the peak RSS in kilobytes, but macOS/BSD report it in bytes;
    divide by 1024 there so the recorded figure is always KB.
    """
    if sys.platform == "darwin":
        return int(ru_maxrss) // 1024
    return int(ru_maxrss)


# --------------------------------------------------------------------------- #
# Small filesystem / git helpers
# --------------------------------------------------------------------------- #
def run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """Run ``git args`` in ``cwd``, capturing output as text."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=check,
        capture_output=True,
        text=True,
    )


def wipe(path: Path) -> None:
    """Remove ``path`` (file or directory tree) if it exists."""
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()


def dir_stats(path: Path) -> dict:
    """Return ``{files, bytes}`` for everything under ``path`` (recursively)."""
    files = 0
    total = 0
    if path.is_dir():
        for p in path.rglob("*"):
            if p.is_file():
                files += 1
                total += p.stat().st_size
    return {"files": files, "bytes": total}


# --------------------------------------------------------------------------- #
# Repo preparation
# --------------------------------------------------------------------------- #
@dataclass
class RepoContext:
    """Resolved on-disk locations and git metadata for one benchmark target."""

    config: RepoConfig
    source_dir: Path  # where the C++ sources live (clone or local working tree)
    bench_dir: Path  # scratch space for outputs/caches/logs (never the source)
    resolved_ref: str
    commit: str

    @property
    def sphinx_src(self) -> Path:
        """Sphinx source dir for the render stage (holds conf.py + index.md)."""
        return self.bench_dir / "sphinx_src"

    @property
    def myst_out(self) -> Path:
        """MyST output dir, placed inside the Sphinx srcdir under api/."""
        return self.sphinx_src / "api"

    @property
    def sphinx_out(self) -> Path:
        """Sphinx HTML output dir (also holds the ``.doctrees`` cache)."""
        return self.bench_dir / "sphinx_out"

    @property
    def cache_dir(self) -> Path:
        """Incremental clangquill ``--cache-dir`` for this target."""
        return self.bench_dir / "cache"

    def doxygen_out(self, mode: str) -> Path:
        """Doxygen output dir for ``mode`` ("xml" or "html")."""
        return self.bench_dir / f"doxygen-{mode}"

    @property
    def logs(self) -> Path:
        """Directory holding captured per-run stdout/stderr logs."""
        return self.bench_dir / "logs"


def prepare_repo(cfg: RepoConfig, work_dir: Path, *, fresh_clone: bool) -> RepoContext:
    """Clone (or locate) ``cfg`` and resolve its pinned ref to a commit."""
    bench_dir = work_dir / "_bench" / cfg.name
    bench_dir.mkdir(parents=True, exist_ok=True)

    if cfg.local:
        source = REPO_ROOT
        commit = run_git(["rev-parse", "HEAD"], source, check=False).stdout.strip()
        return RepoContext(cfg, source, bench_dir, resolved_ref="(local working tree)", commit=commit)

    source = work_dir / cfg.name
    if fresh_clone:
        wipe(source)
    if not source.exists():
        print(f"  cloning {cfg.repo} -> {source}")
        run_git(["clone", "--filter=blob:none", cfg.repo, str(source)], work_dir)

    resolved_ref = cfg.ref
    if cfg.ref:
        checkout = run_git(["checkout", "--force", cfg.ref], source, check=False)
        if checkout.returncode != 0:
            print(f"  WARNING: ref {cfg.ref!r} not found for {cfg.name}; using default branch", file=sys.stderr)
            # Actually move HEAD to the remote default; a failed checkout leaves
            # the worktree where it was, which on a reused clone could be a
            # previously benchmarked ref and diverge from the recorded label.
            run_git(["checkout", "--force", "origin/HEAD"], source, check=False)
            resolved_ref = "(default branch; pinned ref missing)"
    else:
        resolved_ref = "(default branch)"
    commit = run_git(["rev-parse", "HEAD"], source, check=False).stdout.strip()
    return RepoContext(cfg, source, bench_dir, resolved_ref=resolved_ref, commit=commit)


def apply_patch(ctx: RepoContext) -> list[Path]:
    """Append the fixed snippet to each configured target file. Returns them."""
    patched: list[Path] = []
    for rel in ctx.config.patch_files:
        target = ctx.source_dir / rel
        if not target.is_file():
            print(f"  WARNING: patch target {rel!r} missing in {ctx.config.name}", file=sys.stderr)
            continue
        with target.open("a", encoding="utf-8") as fh:
            fh.write(PATCH_SNIPPET)
        patched.append(target)
    return patched


def revert_patch(ctx: RepoContext, patched: list[Path]) -> None:
    """Undo :func:`apply_patch` via ``git checkout`` of the touched files."""
    for target in patched:
        rel = target.relative_to(ctx.source_dir)
        run_git(["checkout", "--", str(rel)], ctx.source_dir, check=False)


def reset_state(ctx: RepoContext) -> None:
    """Return the target to a clean pre-build state between repetitions.

    Generated artifacts (MyST, Sphinx, Doxygen, cache, logs) are removed and any
    lingering patch is reverted. Only the configured ``patch_files`` are
    ``git checkout`` reverted — never the whole tree — so running against a
    ``local`` repo can never clobber the operator's other uncommitted changes
    (the harness only ever edits those patch targets).
    """
    for path in (ctx.sphinx_src, ctx.sphinx_out, ctx.cache_dir, ctx.doxygen_out("xml"), ctx.doxygen_out("html")):
        wipe(path)
    for rel in ctx.config.patch_files:
        run_git(["checkout", "--", rel], ctx.source_dir, check=False)


# --------------------------------------------------------------------------- #
# Stage command builders
# --------------------------------------------------------------------------- #
def clangquill_build_argv(ctx: RepoContext, clangquill_cmd: list[str]) -> list[str]:
    """Build the ``clangquill build`` argv (parse stage, with ``--cache-dir``)."""
    cfg = ctx.config
    argv = [*clangquill_cmd, "build", *cfg.inputs, "-o", str(ctx.myst_out), "--std", cfg.std]
    for inc in cfg.include_dirs:
        argv += ["-I", inc]
    for define in cfg.defines:
        argv += ["-D", define]
    for arg in cfg.compile_args:
        argv += ["--compile-arg", arg]
    argv += ["--cache-dir", str(ctx.cache_dir)]
    return argv


def write_sphinx_scaffold(ctx: RepoContext) -> None:
    """Create a minimal MyST-only Sphinx project around the generated api/."""
    ctx.sphinx_src.mkdir(parents=True, exist_ok=True)
    (ctx.sphinx_src / "conf.py").write_text(
        # A deliberately minimal project: myst_parser only, no clangquill.sphinx_ext
        # (that would re-run the parse inside Sphinx and defeat stage isolation).
        'project = "clangquill benchmark"\n'
        'extensions = ["myst_parser"]\n'
        'html_theme = "alabaster"\n'
        'exclude_patterns = ["_build"]\n'
        'master_doc = "index"\n',
        encoding="utf-8",
    )
    (ctx.sphinx_src / "index.md").write_text(
        "# Benchmark API\n\n```{toctree}\n:maxdepth: 2\n\napi/index\n```\n",
        encoding="utf-8",
    )


def sphinx_argv(ctx: RepoContext, sphinx_cmd: list[str]) -> list[str]:
    """Build the ``sphinx-build`` argv for the render stage (quiet, single-job)."""
    # -q quiet, -j auto would parallelise; keep single-job for fair, stable timing.
    return [*sphinx_cmd, "-b", "html", "-q", str(ctx.sphinx_src), str(ctx.sphinx_out)]


def write_doxyfile(ctx: RepoContext, mode: str) -> Path:
    """Generate a minimal Doxyfile for ``mode`` ("xml" or "html")."""
    cfg = ctx.config
    out_dir = ctx.doxygen_out(mode)
    out_dir.mkdir(parents=True, exist_ok=True)
    inputs = " ".join(shlex.quote(str(ctx.source_dir / d)) for d in cfg.doxygen_input)
    common = [
        f'PROJECT_NAME = "{cfg.name}"',
        f"OUTPUT_DIRECTORY = {out_dir}",
        f"INPUT = {inputs}",
        "RECURSIVE = YES",
        "QUIET = YES",
        "WARNINGS = NO",
        "WARN_IF_UNDOCUMENTED = NO",
        "GENERATE_LATEX = NO",
        "EXTRACT_ALL = YES",
        # Keep both tools single-threaded and graphviz-free for a fair comparison.
        "HAVE_DOT = NO",
    ]
    if mode == "xml":
        common += ["GENERATE_XML = YES", "GENERATE_HTML = NO", "XML_OUTPUT = xml"]
    else:
        common += [
            "GENERATE_XML = NO",
            "GENERATE_HTML = YES",
            "HTML_OUTPUT = html",
            "SEARCHENGINE = NO",
        ]
    doxyfile = out_dir / "Doxyfile"
    doxyfile.write_text("\n".join(common) + "\n", encoding="utf-8")
    return doxyfile


def doxygen_argv(doxygen_cmd: list[str], doxyfile: Path) -> list[str]:
    """Build the ``doxygen`` argv that runs ``doxyfile``."""
    return [*doxygen_cmd, str(doxyfile)]


# --------------------------------------------------------------------------- #
# Work metrics (a coarse "how much did the tool actually produce" signal)
# --------------------------------------------------------------------------- #
def clangquill_work(stdout: str) -> dict:
    """Extract symbol/file/page counts from ``clangquill build`` output."""
    work: dict = {}
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith("Parsed "):
            parts = line.replace("(s)", "").split()
            # "Parsed N symbol from M file."
            with contextlib.suppress(ValueError, IndexError):
                work["symbols"] = int(parts[1])
                work["files"] = int(parts[4])
        elif line.startswith("Wrote "):
            parts = line.split()
            with contextlib.suppress(ValueError, IndexError):
                work["pages_written"] = int(parts[1])
    return work


# --------------------------------------------------------------------------- #
# Scenario execution per stage
# --------------------------------------------------------------------------- #
@dataclass
class Tools:
    """Resolved command (argv prefix) for each external tool the harness drives."""

    clangquill: list[str]
    sphinx: list[str]
    doxygen: list[str]


def _stage_log(ctx: RepoContext, stage: str, scenario: str, rep: int) -> Path:
    """Path of the captured log for one ``(stage, scenario, rep)`` run."""
    return ctx.logs / f"{stage}.{scenario}.{rep}.log"


def run_stage(
    ctx: RepoContext,
    stage: str,
    scenarios: list[str],
    tools: Tools,
    repeat: int,
    warmup: int,
) -> dict:
    """Measure ``stage`` for ``ctx`` across the requested scenarios.

    Returns a nested dict ``{scenario: {"samples": [...], "stats": {...}, ...}}``.
    Each repetition resets to a clean state, then runs the cold / noop /
    incremental sequence so the three scenarios share one warmed clone but
    independent build state.
    """

    # ``cold_prep`` produces the timed command's *preconditions* from a clean
    # state; ``incr_prep`` refreshes them after the patch is applied. Both return
    # the timed (argv, cwd) plus a work-metric extractor and the output dir to
    # size up afterwards.
    def myst_cmd() -> tuple[list[str], Path]:
        """Return the timed command + cwd for the clangquill parse stage."""
        return clangquill_build_argv(ctx, tools.clangquill), ctx.source_dir

    def sphinx_cmd() -> tuple[list[str], Path]:
        """Return the timed command + cwd for the Sphinx render stage."""
        return sphinx_argv(ctx, tools.sphinx), ctx.sphinx_src

    def doxy_cmd(mode: str) -> tuple[list[str], Path]:
        """Return the timed command + cwd for the Doxygen ``mode`` stage."""
        return doxygen_argv(tools.doxygen, write_doxyfile(ctx, mode)), ctx.source_dir

    def untimed(argv: list[str], cwd: Path, tag: str) -> None:
        """Run ``argv`` for its side effects (e.g. produce MyST), discarding timing."""
        measure(argv, cwd, ctx.logs / f"_prep.{tag}.log")

    results: dict = {sc: {"samples": []} for sc in scenarios}
    total_passes = warmup + repeat

    for pass_idx in range(total_passes):
        recording = pass_idx >= warmup
        rep = pass_idx - warmup
        reset_state(ctx)

        # -- cold ----------------------------------------------------------- #
        if stage == "clangquill-sphinx":
            write_sphinx_scaffold(ctx)
            untimed(*myst_cmd(), tag=f"sphinx-cold-myst-{pass_idx}")  # produce MyST first
            argv, cwd = sphinx_cmd()
            out_dir = ctx.sphinx_out
        elif stage == "clangquill-myst":
            write_sphinx_scaffold(ctx)
            argv, cwd = myst_cmd()
            out_dir = ctx.myst_out
        else:  # doxygen-xml / doxygen-html
            mode = stage.split("-", 1)[1]
            argv, cwd = doxy_cmd(mode)
            out_dir = ctx.doxygen_out(mode)
        cold = measure(argv, cwd, _stage_log(ctx, stage, "cold", rep))
        cold_output = dir_stats(out_dir)

        # -- noop ----------------------------------------------------------- #
        if stage == "clangquill-sphinx":
            untimed(*myst_cmd(), tag=f"sphinx-noop-myst-{pass_idx}")
        noop = measure(argv, cwd, _stage_log(ctx, stage, "noop", rep)) if "noop" in scenarios else None
        noop_output = dir_stats(out_dir) if noop is not None else None

        # -- incremental ---------------------------------------------------- #
        incr = None
        incr_output = None
        if "incremental" in scenarios:
            patched = apply_patch(ctx)
            try:
                if stage == "clangquill-sphinx":
                    # Regenerate MyST so the render sees the change, then time render.
                    untimed(*myst_cmd(), tag=f"sphinx-incr-myst-{pass_idx}")
                incr = measure(argv, cwd, _stage_log(ctx, stage, "incremental", rep))
                incr_output = dir_stats(out_dir)
            finally:
                revert_patch(ctx, patched)

        if not recording:
            continue
        # Each scenario records the output snapshot taken right after it ran;
        # a single shared snapshot would mislabel cold/noop with the patched
        # incremental tree (the scenarios rebuild the same out_dir in turn).
        for scenario, m, output in (
            ("cold", cold, cold_output),
            ("noop", noop, noop_output),
            ("incremental", incr, incr_output),
        ):
            if scenario not in scenarios or m is None:
                continue
            sample = m.as_dict()
            if stage == "clangquill-myst":
                sample["work"] = clangquill_work(m.stdout)
            sample["output"] = output
            results[scenario]["samples"].append(sample)

    for scenario in scenarios:
        results[scenario]["stats"] = summarize([s["wall_s"] for s in results[scenario]["samples"]])
    return results


def summarize(values: list[float]) -> dict:
    """Min / median / mean / stddev for a list of measurements."""
    if not values:
        return {}
    return {
        "n": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "stddev": statistics.stdev(values) if len(values) > 1 else 0.0,
    }


# --------------------------------------------------------------------------- #
# Environment / tool metadata
# --------------------------------------------------------------------------- #
def tool_version(argv: list[str]) -> str:
    """Return the first line of ``argv`` output (e.g. ``--version``), or ""."""
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
        if out.returncode != 0:
            return ""
        text = (out.stdout or out.stderr).strip()
        return text.splitlines()[0] if text else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


def libclang_version() -> str:
    """Return the linked libclang version string, or "" if unavailable."""
    try:
        from clangquill import _core  # noqa: PLC0415

        return str(_core.libclang_version())
    except Exception:
        return ""


def total_ram_gb() -> float:
    """Return total physical RAM in GB (0.0 if it cannot be determined)."""
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9, 1)
    except (ValueError, OSError):
        return 0.0


def environment_info(tools: Tools) -> dict:
    """Collect machine, Python and tool/toolchain versions for the report."""
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "ram_gb": total_ram_gb(),
        "python": platform.python_version(),
        "tools": {
            "clangquill": tool_version([*tools.clangquill, "--version"]),
            "sphinx": tool_version([*tools.sphinx, "--version"]),
            "doxygen": tool_version([*tools.doxygen, "--version"]),
            "libclang": libclang_version(),
        },
    }


def available_stages(requested: list[str], tools: Tools) -> list[str]:
    """Filter ``requested`` (already-validated) stages to those whose tool is installed.

    A stage whose backing tool is missing is skipped with a warning; unknown
    stage names are rejected earlier in :func:`main` so they never reach here.
    """
    have_clangquill = shutil.which(tools.clangquill[0]) is not None
    have_sphinx = shutil.which(tools.sphinx[0]) is not None and _have_myst()
    have_doxygen = shutil.which(tools.doxygen[0]) is not None
    keep: list[str] = []
    for stage in requested:
        if stage == "clangquill-myst" and not have_clangquill:
            print(f"  skipping {stage}: '{tools.clangquill[0]}' not found", file=sys.stderr)
            continue
        if stage == "clangquill-sphinx" and not (have_clangquill and have_sphinx):
            print(f"  skipping {stage}: needs clangquill + sphinx-build + myst-parser", file=sys.stderr)
            continue
        if stage.startswith("doxygen") and not have_doxygen:
            print(f"  skipping {stage}: '{tools.doxygen[0]}' not found", file=sys.stderr)
            continue
        keep.append(stage)
    return keep


def _have_myst() -> bool:
    """Return whether the ``myst_parser`` Sphinx extension is importable."""
    import importlib.util  # noqa: PLC0415

    return importlib.util.find_spec("myst_parser") is not None


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def _median(results: dict, repo: str, stage: str, scenario: str) -> float | None:
    """Return the median wall time for one result cell, or None if absent."""
    try:
        return results[repo][stage][scenario]["stats"]["median"]
    except (KeyError, TypeError):
        return None


def _fmt(value: float | None) -> str:
    """Format a seconds value to 3 decimals, or an em dash when None."""
    return f"{value:.3f}" if value is not None else "—"


def render_markdown(payload: dict) -> str:
    """Render the results ``payload`` as a Markdown report."""
    env = payload["environment"]
    lines: list[str] = ["# ClangQuill vs Doxygen benchmark", ""]
    lines.append(f"- Generated: `{env['timestamp']}`")
    lines.append(f"- Machine: {env['platform']} · {env['cpu_count']} CPU · {env['ram_gb']} GB RAM")
    lines.append(
        f"- clangquill: `{env['tools']['clangquill'] or 'n/a'}` · libclang `{env['tools']['libclang'] or 'n/a'}`",
    )
    lines.append(f"- doxygen: `{env['tools']['doxygen'] or 'n/a'}` · sphinx: `{env['tools']['sphinx'] or 'n/a'}`")
    lines.append(f"- repeat={payload['repeat']} warmup={payload['warmup']} (median wall-clock seconds)")
    lines.append("")

    scenarios = payload["scenarios"]
    for repo, repo_data in payload["results"].items():
        meta = payload["repos"][repo]
        lines.append(f"## {repo}")
        lines.append(f"_ref: {meta['resolved_ref']} · commit: `{meta['commit'][:12] or 'n/a'}`_")
        lines.append("")
        header = "| stage | " + " | ".join(scenarios) + " |"
        sep = "| --- | " + " | ".join("---" for _ in scenarios) + " |"
        lines += [header, sep]
        for stage in ALL_STAGES:
            if stage not in repo_data:
                continue
            cells = [_fmt(_median(payload["results"], repo, stage, sc)) for sc in scenarios]
            lines.append(f"| {stage} | " + " | ".join(cells) + " |")
        lines.append("")

        # Derived comparisons.
        lines += _derived_lines(payload["results"], repo, scenarios)
        lines.append("")
    return "\n".join(lines)


def _derived_lines(results: dict, repo: str, scenarios: list[str]) -> list[str]:
    """Build the per-repo derived parse/full-HTML comparison and cache-speedup lines."""
    out: list[str] = []
    for scenario in scenarios:
        myst = _median(results, repo, "clangquill-myst", scenario)
        sphinx = _median(results, repo, "clangquill-sphinx", scenario)
        dox_xml = _median(results, repo, "doxygen-xml", scenario)
        dox_html = _median(results, repo, "doxygen-html", scenario)
        bits: list[str] = []
        if myst is not None and myst > 0 and dox_xml is not None and dox_xml > 0:
            bits.append(f"parse: clangquill-myst {myst:.3f}s vs doxygen-xml {dox_xml:.3f}s ({dox_xml / myst:.2f}× )")
        if myst is not None and sphinx is not None and (myst + sphinx) > 0:
            full = myst + sphinx
            tail = ""
            if dox_html is not None and dox_html > 0:
                tail = f" vs doxygen-html {dox_html:.3f}s ({dox_html / full:.2f}× )"
            bits.append(f"full HTML: clangquill {full:.3f}s{tail}")
        if bits:
            out.append(f"- **{scenario}** — " + "; ".join(bits))
    # The headline incremental story.
    cold = _median(results, repo, "clangquill-myst", "cold")
    noop = _median(results, repo, "clangquill-myst", "noop")
    incr = _median(results, repo, "clangquill-myst", "incremental")
    if cold and noop:
        out.append(
            f"- **clangquill cache** — cold→noop {cold / noop:.1f}× faster"
            + (f", cold→incremental {cold / incr:.1f}× faster" if incr else ""),
        )
    return out


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the benchmark CLI arguments."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    p.add_argument("--repos", default="", help="Comma-separated repo names to run (default: all configs).")
    p.add_argument("--scenarios", default=",".join(ALL_SCENARIOS))
    p.add_argument("--tools", default=",".join(ALL_STAGES), help="Comma-separated stages to run.")
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--warmup", type=int, default=1)
    p.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    p.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    p.add_argument("--clangquill", default="clangquill")
    p.add_argument("--sphinx", default="sphinx-build")
    p.add_argument("--doxygen", default="doxygen")
    p.add_argument("--fresh-clone", action="store_true", help="Re-clone even if a clone already exists.")
    p.add_argument("--keep-clones", action="store_true", help="(default) keep clones for reuse; here for clarity.")
    return p.parse_args(argv)


def load_configs(config_dir: Path, repos: str) -> list[RepoConfig]:
    """Load TOML configs from ``config_dir``, filtered to ``repos`` when given."""
    wanted = {r.strip() for r in repos.split(",") if r.strip()}
    configs: list[RepoConfig] = []
    for path in sorted(config_dir.glob("*.toml")):
        cfg = RepoConfig.from_toml(path)
        if wanted and cfg.name not in wanted:
            continue
        configs.append(cfg)
    return configs


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark CLI: drive every repo/stage and write the reports."""
    args = parse_args(argv)
    tools = Tools(
        clangquill=shlex.split(args.clangquill),
        sphinx=shlex.split(args.sphinx),
        doxygen=shlex.split(args.doxygen),
    )
    requested_stages = [s.strip() for s in args.tools.split(",") if s.strip()]
    unknown = [s for s in requested_stages if s not in ALL_STAGES]
    if unknown:
        # A typo'd --tools value (easy to miss in a workflow_dispatch input) is a
        # CLI error, not something to silently skip into a partial report.
        print(f"Unknown stage(s): {', '.join(unknown)}. Valid stages: {', '.join(ALL_STAGES)}", file=sys.stderr)
        return 2
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    stages = available_stages(requested_stages, tools)
    if not stages:
        print("No runnable stages — install clangquill / sphinx-build+myst-parser / doxygen.", file=sys.stderr)
        return 1

    configs = load_configs(args.config_dir, args.repos)
    if not configs:
        print(f"No configs found in {args.config_dir}", file=sys.stderr)
        return 1

    args.work_dir.mkdir(parents=True, exist_ok=True)
    env_info = environment_info(tools)

    payload: dict = {
        "environment": env_info,
        "repeat": args.repeat,
        "warmup": args.warmup,
        "scenarios": scenarios,
        "stages": stages,
        "repos": {},
        "results": {},
    }

    for cfg in configs:
        print(f"\n=== {cfg.name} ===")
        ctx = prepare_repo(cfg, args.work_dir, fresh_clone=args.fresh_clone)
        payload["repos"][cfg.name] = {"resolved_ref": ctx.resolved_ref, "commit": ctx.commit, "repo": cfg.repo}
        payload["results"][cfg.name] = {}
        for stage in stages:
            print(f"  [{stage}] {scenarios} x{args.repeat} (+{args.warmup} warmup)")
            try:
                payload["results"][cfg.name][stage] = run_stage(
                    ctx,
                    stage,
                    scenarios,
                    tools,
                    args.repeat,
                    args.warmup,
                )
            except Exception as exc:
                print(f"    ERROR in {stage}: {exc}", file=sys.stderr)
                payload["results"][cfg.name][stage] = {"error": str(exc)}

    args.results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = args.results_dir / f"{stamp}.json"
    md_path = args.results_dir / f"{stamp}.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown = render_markdown(payload)
    md_path.write_text(markdown, encoding="utf-8")

    print("\n" + markdown)
    print(f"\nWrote {json_path}\n      {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
