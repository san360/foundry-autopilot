import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(PWSH is None, reason="PowerShell 7 is required")

# Shadow every external operation the publish script uses, even for the publish
# branch exercised by the parity test. No test authenticates or reaches a service.
HARNESS = r"""
$ErrorActionPreference = "Stop"
function az {
    if ($env:TEST_MODE -ne "publish") { throw "Preview attempted Azure authentication" }
    $global:LASTEXITCODE = 0
    return "test-token"
}
function azd {
    if ($env:TEST_MODE -ne "publish") { throw "Preview attempted an azd write" }
    $global:LASTEXITCODE = 0
}
function Invoke-RestMethod {
    param($Uri, $Method, $Headers, $Body)
    if ($env:TEST_MODE -ne "publish") { throw "Preview attempted a REST call" }
    Set-Content -LiteralPath $env:TEST_CAPTURE -Value $Body -Encoding utf8
    return @{ teamsAppId = "test-app" }
}
$parameters = @{ BlueprintClientId = "<blueprint-client-id>" }
if ($env:TEST_MODE -eq "preview") { $parameters.Preview = $true }
if ($env:TEST_OUTPUT) { $parameters.OutputPath = $env:TEST_OUTPUT }
try {
    $result = & $env:TEST_SCRIPT @parameters
    if ($env:TEST_MODE -eq "preview") {
        $result | Set-Content -LiteralPath $env:TEST_CAPTURE -Encoding utf8
    }
} catch {
    Write-Error $_
    exit 1
}
"""


@pytest.fixture
def publish_env(tmp_path):
    for name in ("publish-digital-worker.ps1", "common.ps1"):
        shutil.copyfile(ROOT / "scripts" / name, tmp_path / name)
    env = os.environ.copy()
    for name in (
        "AUTOPILOT_SCENARIO", "AGENT_APP_VERSION", "AGENT_DISPLAY_NAME",
        "AGENT_DEVELOPER_NAME", "CAN_RESPOND_WITHOUT_MENTION",
        "INCLUDE_AGENTIC_USER_TEMPLATE", "SEARCH_TOKEN_FLOW", "AZD_KEY_PREFIX",
        "AZURE_AI_PROJECT_ENDPOINT", "AGENT_NAME", "LOCATION", "SUBSCRIPTION_ID",
        "AZURE_SUBSCRIPTION_ID", "TEST_OUTPUT",
    ):
        env.pop(name, None)
    env.update(
        TEST_SCRIPT=str(tmp_path / "publish-digital-worker.ps1"),
        TEST_CAPTURE=str(tmp_path / "capture.json"),
        SUBSCRIPTION_ID="test-subscription",
    )
    return env


def run_script(env):
    return subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", HARNESS],
        env=env, capture_output=True, text=True, timeout=30,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"AUTOPILOT_SCENARIO": "rfp", "SEARCH_TOKEN_FLOW": "agent_user",
         "INCLUDE_AGENTIC_USER_TEMPLATE": "true"},
        {"AGENT_APP_VERSION": "1.0.7", "AGENT_DISPLAY_NAME": "Preview agent",
         "AGENT_DEVELOPER_NAME": "Example developer", "CAN_RESPOND_WITHOUT_MENTION": "true"},
    ],
)
def test_preview_matches_publish_body_without_external_calls(publish_env, tmp_path, overrides):
    publish_env.update(overrides, TEST_MODE="preview", TEST_OUTPUT=str(tmp_path / "preview.json"))
    preview = run_script(publish_env)
    assert preview.returncode == 0, preview.stderr
    emitted = json.loads(Path(publish_env["TEST_CAPTURE"]).read_text(encoding="utf-8-sig"))
    written = json.loads(Path(publish_env["TEST_OUTPUT"]).read_text(encoding="utf-8-sig"))
    assert emitted == written
    assert "not a generated or exported Microsoft 365 app manifest" in preview.stdout
    if overrides.get("INCLUDE_AGENTIC_USER_TEMPLATE") == "true":
        assert written["agenticUserTemplate"]["AgentIdentityBlueprintId"] == "<blueprint-client-id>"
        assert written["optionalPermissionScopes"][-1]["scopes"] == ["user_impersonation"]
    else:
        assert "agenticUserTemplate" not in written
    if overrides.get("AGENT_APP_VERSION"):
        assert written["appVersion"] == "1.0.7"
        assert written["agentDisplayName"] == "Preview agent"
        assert written["canRespondWithoutMention"] is True

    publish_env.update(TEST_MODE="publish")
    publish_env.pop("TEST_OUTPUT")
    published = run_script(publish_env)
    assert published.returncode == 0, published.stderr
    assert json.loads(Path(publish_env["TEST_CAPTURE"]).read_text(encoding="utf-8-sig")) == written


def test_preview_stdout_only(publish_env, tmp_path):
    publish_env.update(TEST_MODE="preview")
    result = run_script(publish_env)
    assert result.returncode == 0, result.stderr
    body = json.loads(Path(publish_env["TEST_CAPTURE"]).read_text(encoding="utf-8-sig"))
    assert body["publishAsAutopilot"] is True
    assert body["publishScope"] == "Tenant"
    assert {p.name for p in tmp_path.iterdir()} == {
        "common.ps1", "publish-digital-worker.ps1", "capture.json",
    }


def test_output_path_without_preview_fails_before_external_calls(publish_env, tmp_path):
    publish_env.update(TEST_MODE="blocked", TEST_OUTPUT=str(tmp_path / "preview.json"))
    result = run_script(publish_env)
    assert result.returncode != 0
    assert "OutputPath requires -Preview" in result.stderr
    assert not Path(publish_env["TEST_OUTPUT"]).exists()
    assert not Path(publish_env["TEST_CAPTURE"]).exists()


def test_preview_file_error_is_not_silently_ignored(publish_env, tmp_path):
    publish_env.update(TEST_MODE="preview", TEST_OUTPUT=str(tmp_path / "missing" / "preview.json"))
    result = run_script(publish_env)
    assert result.returncode != 0
    assert not Path(publish_env["TEST_CAPTURE"]).exists()
