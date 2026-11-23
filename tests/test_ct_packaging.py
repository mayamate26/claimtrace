"""Packaging metadata: the PyPI name `claimtrace` belongs to an unrelated project, so everything
that installs or runs this client must point at `claimtrace-mcp`."""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
tomllib = pytest.importorskip("tomllib") if sys.version_info >= (3, 11) else pytest.importorskip("tomli")


def _project():
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def test_distribution_name_and_required_mcp_dependency():
    project = _project()
    assert project["name"] == "claimtrace-mcp"
    assert "mcp>=1.2" in project["dependencies"]
    assert "mcp" not in project.get("optional-dependencies", {})


def test_console_scripts():
    assert _project()["scripts"] == {"claimtrace": "claimtrace_mcp.cli:main",
                                     "claimtrace-mcp": "claimtrace_mcp.mcp_server:main"}


def test_import_package_is_renamed():
    assert (ROOT / "claimtrace_mcp" / "__init__.py").is_file()
    assert not (ROOT / "claimtrace").exists()


def test_server_json_points_at_claimtrace_mcp_with_no_runtime_arguments():
    data = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    assert data["name"] == "com.mayamate/claimtrace"
    (pkg,) = data["packages"]
    assert pkg["registryType"] == "pypi" and pkg["identifier"] == "claimtrace-mcp"
    assert pkg["runtimeHint"] == "uvx" and pkg["transport"] == {"type": "stdio"}
    assert "runtimeArguments" not in pkg and "packageArguments" not in pkg
    assert pkg["version"] == data["version"] == _project()["version"]


def test_readme_install_and_mcp_commands():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "<!-- mcp-name: com.mayamate/claimtrace -->" in readme
    assert "pip install claimtrace-mcp" in readme
    assert '"args": ["claimtrace-mcp"]' in readme and "uvx claimtrace-mcp" in readme
    assert not re.search(r"pip install '?claimtrace(\[|'|\s|$)", readme)
    assert "claimtrace[mcp]" not in readme and "uvx claimtrace " not in readme


def test_action_installs_and_runs_the_renamed_package():
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    assert 'pip install --quiet --disable-pip-version-check "$GITHUB_ACTION_PATH"' in action
    assert "python -m claimtrace_mcp.action_runner" in action


def test_github_references_point_at_mayamate26():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    example = (ROOT / "examples" / "claimtrace.yml").read_text(encoding="utf-8")
    for text in (readme, example, (ROOT / "server.json").read_text(encoding="utf-8"),
                 (ROOT / "pyproject.toml").read_text(encoding="utf-8")):
        assert not re.search(r"(?<![\w.])mayamate/claimtrace(?!\s*-->)", text.replace("com.mayamate/claimtrace", ""))
    assert "uses: mayamate26/claimtrace@v0" in readme and "uses: mayamate26/claimtrace@v0" in example
    assert readme.index("git+https://github.com/mayamate26/claimtrace") < readme.index("pip install claimtrace-mcp")
    assert "pip install git+https://github.com/mayamate26/claimtrace" in readme
    assert "uvx --from git+https://github.com/mayamate26/claimtrace claimtrace-mcp" in readme
    assert _project()["urls"]["Repository"] == "https://github.com/mayamate26/claimtrace"
    assert not (ROOT / ".github" / "workflows").exists()
