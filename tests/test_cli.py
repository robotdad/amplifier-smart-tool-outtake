import json
import os
import subprocess
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest


@pytest.mark.parametrize("flag", ["-V", "--version"])
def test_version_flags(flag):
    from outtake import manifest

    result = call(flag)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{manifest()['version']}\n"
    assert result.stderr == ""


def test_manifest_version_matches_project():
    from outtake import manifest

    project = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert manifest()["version"] == project["project"]["version"]


def test_manifest_version_matches_installed_metadata():
    from outtake import manifest

    try:
        installed = version("outtake")
    except PackageNotFoundError:
        pytest.skip("Outtake distribution metadata is not installed.")
    assert manifest()["version"] == installed


def test_help_version_headers_match_library():
    from outtake import manifest, skill
    from outtake.help import command_names

    header = f"Version: {manifest()['version']}"
    for command in (None, *command_names()):
        result = call(*([] if command is None else [command]), "--help")
        assert result.returncode == 0, (command, result.stderr)
        assert result.stderr == ""
        assert result.stdout == skill(command) + "\n"
        lines = result.stdout.splitlines()
        assert [line for line in lines if line.startswith("Version:")] == [header]
        repository = next(i for i, line in enumerate(lines) if line.startswith("Repository:"))
        assert lines[repository + 1] == header
        assert repository + 1 < next(i for i, line in enumerate(lines) if line.startswith("# "))


def test_version_and_help_without_optional_backends():
    script = """
import contextlib
import importlib.abc
import io
import sys

class BlockOptionalBackends(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {
            "amplifier_agent_lib", "mcp", "openai", "anthropic", "google", "copilot"
        }:
            raise AssertionError(f"Optional backend imported: {fullname}")

sys.meta_path.insert(0, BlockOptionalBackends())
from outtake import manifest, skill
from outtake.cli import main
from outtake.help import command_names

expected = manifest()["version"]
for arguments, output in [
    (["-V"], expected),
    (["--version"], expected),
    (["--help"], skill()),
    *[([command, "--help"], skill(command)) for command in command_names()],
]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            code = main(arguments)
        except SystemExit as exc:
            code = exc.code
    assert code == 0, (arguments, code, stderr.getvalue())
    assert stdout.getvalue() == output + "\\n", arguments
    assert stderr.getvalue() == "", arguments
"""
    result = subprocess.run(
        [sys.executable, "-c", script], text=True, capture_output=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr


def call(*arguments, input=None):
    # Deterministic paths never need provider environment configuration.
    env = {
        k: v
        for k, v in os.environ.items()
        if not any(
            word in k.upper()
            for word in ("API_KEY", "OPENAI", "ANTHROPIC", "GEMINI", "GOOGLE", "PROVIDER")
        )
    }
    return subprocess.run(
        ["outtake", *arguments], input=input, text=True, capture_output=True, env=env, timeout=30
    )


def test_help_manifest_schemas_and_failure():
    assert "<skill_content" in call("--help").stdout
    assert "plan" in call("-h").stdout
    assert json.loads(call("manifest").stdout)["name"] == "outtake"
    assert "plan" in json.loads(call("schemas").stdout)
    assert call("not-a-command").returncode != 0


def test_cli_plan_render_and_empty_stdin(tool, fixture_video, tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(tool.settings.model_dump_json())
    response = call(
        "plan",
        "--settings",
        str(settings),
        input=json.dumps({"source": str(fixture_video), "start": 0.95, "end": 2, "format": "png"}),
    )
    assert response.returncode == 0, response.stdout + response.stderr
    plan = json.loads(response.stdout)
    rendered = call("render", "--settings", str(settings), input=json.dumps({"plan": plan}))
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    assert json.loads(rendered.stdout)["resolved_start"] == 1
    assert call("plan", "--settings", str(settings), input="").returncode == 2


def test_every_command_has_library_owned_skill_and_terse_help():
    import re
    from pathlib import Path

    from outtake import skill
    from outtake.capabilities import OPERATIONS
    from outtake.help import GUIDANCE, command_names

    assert set(GUIDANCE) == set(OPERATIONS)
    for command in command_names():
        result = call(command, "--help")
        assert result.returncode == 0, (command, result.stderr)
        assert result.stdout.strip() == skill(command)
        assert result.stdout.startswith(f'<skill_content name="outtake-{command}">')
        assert result.stdout.rstrip().endswith("</skill_content>")
        for section in (
            "Arguments and defaults",
            "Example",
            "Result and side effects",
            "Failures and recovery",
        ):
            assert f"## {section}" in result.stdout
        assert len(result.stdout.splitlines()) < 500
        root = Path(re.search(r"Skill directory: (.+)", result.stdout)[1])
        for resource in re.findall(r"<file>(.+?)</file>", result.stdout):
            assert (root / resource).is_file()
        terse = call(command, "-h")
        assert terse.returncode == 0 and "usage:" in terse.stdout
        assert "<skill_content" not in terse.stdout
    assert call("not-a-command", "--help").returncode == 2
    assert call("render", "--settings", "/missing/settings.json", "--help").returncode == 0


def test_render_help_example_runs_with_retained_plan(tool, fixture_video, tmp_path):
    import re
    import sys

    settings = tmp_path / "settings.json"
    settings.write_text(tool.settings.model_dump_json())
    plan = tool.plan(str(fixture_video), 0.5, 1.5, captions_enabled=False)
    (tmp_path / "plan.json").write_text(plan.model_dump_json())
    help_text = call("render", "--help").stdout
    snippet = re.search(r"python - <<'PY' > request.json\n(.*?)\nPY", help_text, re.S)[1]
    example = subprocess.run(
        [sys.executable, "-c", snippet], cwd=tmp_path, text=True, capture_output=True, check=True
    )
    request = json.loads(example.stdout)
    assert request["plan"]["id"] == plan.id
    result = call("render", "--settings", str(settings), input=example.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["plan"]["id"] == plan.id and receipt["bytes"] > 0
    assert "model-backed; consumes provider tokens" in call("find", "--help").stdout
    assert (
        "Local OCR" in call("convert-captions", "--help").stdout
        or "local Tesseract" in call("convert-captions", "--help").stdout
    )
