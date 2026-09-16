import json
import os
import subprocess


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
