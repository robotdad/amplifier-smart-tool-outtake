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
