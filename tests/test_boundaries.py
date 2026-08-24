"""ADR-0012 enforcement: user data never touches the git tree, structurally.

Two layers: a source scan proving cli/paths.py is the only module that names
repo-relative data locations, and a runtime write-audit proving a real
pipeline run (extract → classify → report) leaves the repo byte-identical.
A convention that depends on remembering breaks; these fail instead.
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import REPO

# The single sanctioned repo-data path authority (ADR-0012). pricing_update
# writes harness/replay/pricing_snapshots/ — reference data, not user data —
# and does not construct data/ paths, so it needs no entry here.
ALLOWED = {"caliper/cli/paths.py"}

# Path-construction spellings; prose in docstrings/comments doesn't match.
PATTERNS = ('"data" /', '/ "data"', "'data' /", "/ 'data'",
            '"data",', "'data',")


def _production_modules() -> list[Path]:
    out = []
    for pkg in ("caliper",):
        out.extend(p for p in (REPO / pkg).rglob("*.py")
                   if "__pycache__" not in p.parts)
    return out


def test_only_paths_module_constructs_repo_data_paths():
    offenders = []
    for py in _production_modules():
        rel = py.relative_to(REPO).as_posix()
        if rel in ALLOWED:
            continue
        src = py.read_text()
        for pat in PATTERNS:
            if pat in src:
                offenders.append(f"{rel}: {pat!r}")
    assert not offenders, (
        "repo-relative data paths constructed outside cli/paths.py "
        f"(ADR-0012): {offenders}")


def _snapshot_repo_data() -> dict[str, tuple[int, int]]:
    out = {}
    for p in (REPO / "data").rglob("*"):
        if p.is_file():
            st = p.stat()
            out[str(p)] = (st.st_mtime_ns, st.st_size)
    return out


def test_pipeline_writes_nothing_into_the_repo(run_extract):
    """The structural guarantee, exercised: a full extract → classify →
    report run under a sandboxed CALIPER_HOME must leave the repo's data
    tree byte-identical — whatever path expression a writer used."""
    from caliper.cli.main import main
    from caliper.cli.paths import derived_dir, reports_dir, state_dir

    before = _snapshot_repo_data()

    _, data_dir = run_extract()  # extraction into a tmp tree
    # stage the sandboxed home so report has sessions to render (the
    # empty-state path exits before writing, by design)
    import shutil
    from caliper.cli.paths import extracted_dir
    shutil.copytree(data_dir, extracted_dir(), dirs_exist_ok=True)
    # keep report generation off the machine's real sources: an empty name
    # map short-circuits build_name_map's live discovery
    state_dir().mkdir(parents=True, exist_ok=True)
    (state_dir() / ".project_names.json").write_text("{}")

    assert main(["classify", "--data-dir", str(data_dir)]) == 0
    assert main(["report"]) == 0

    # everything landed under the sandboxed home...
    assert (derived_dir() / "classes" / "task_classes.jsonl").exists()
    assert (reports_dir() / "first_look.html").exists()
    # ...and the repo is untouched
    assert _snapshot_repo_data() == before


def test_evidence_tree_is_never_a_write_target():
    """Evidence is read-fallback only: no production module outside
    cli/paths.py may name the data/evidence tree at all."""
    for py in _production_modules():
        rel = py.relative_to(REPO).as_posix()
        if rel in ALLOWED:
            continue
        src = py.read_text()
        # path spellings only — "evidence" is also a routing_policy schema
        # field, which is data access, not a filesystem location
        assert "data/evidence" not in src \
            and '"evidence" /' not in src and '/ "evidence"' not in src, \
            f"{rel} references the evidence tree directly (ADR-0012)"
