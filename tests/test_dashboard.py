"""Exercise the adapter through HTTP and real browser-decoded artifacts."""

import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from playwright.sync_api import expect, sync_playwright


def request(server, path, body=None, **headers):
    headers = {"Authorization": f"Bearer {server.token}", **headers}
    if body is not None:
        headers["Content-Type"] = "application/json"
    return urlopen(
        Request(
            server.origin + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
        )
    )


def call(server, operation, arguments=None):
    started = json.load(
        request(server, "/api/call", {"operation": operation, "arguments": arguments or {}})
    )
    for _ in range(300):
        job = json.load(request(server, "/api/jobs/" + started["job_id"]))
        if job["status"] != "running":
            return job
        time.sleep(0.02)
    pytest.fail("Dashboard job did not terminate")


def test_http_scope_ranges_and_shared_settings(tool, fixture_video, tmp_path):
    plan = tool.plan(str(fixture_video), 0, 1, format="png")
    receipt = tool.render(plan)
    with tool.dashboard(plan_id=plan.id) as server:
        for headers in [
            {"Authorization": "wrong"},
            {"Origin": "https://example.org"},
            {"Host": "other.example"},
        ]:
            with pytest.raises(HTTPError) as denied:
                request(server, "/api/jobs/unknown", **headers)
            assert denied.value.code == 403
        with pytest.raises(HTTPError) as denied:
            request(server, "/media/export/../../etc/passwd")
        assert denied.value.code == 404
        media = request(server, "/media/export/" + receipt["artifact_id"], Range="bytes=0-7")
        assert media.status == 206 and media.read() == b"\x89PNG\r\n\x1a\n"
        assert call(server, "get_plan", {"plan_id": plan.id})["result"]["id"] == plan.id
        settings = tool.settings.model_dump(mode="json")
        settings["output_root"] = str(tmp_path / "other-outputs")
        result = call(server, "configure", {"settings": settings, "appearance": "light"})
        assert result["status"] == "complete"
        assert tool.preferences()["appearance"] == "light"
        assert tool.output == tmp_path / "other-outputs"
        from outtake import Outtake

        reopened = Outtake(settings)
        assert reopened.restore_configuration()["settings"]["output_root"] == str(tool.output)


def test_browser_edit_preview_export_reopen(tool, fixture_video, tmp_path):
    plan = tool.plan(str(fixture_video), 0, 2)
    errors = []
    with tool.dashboard(plan_id=plan.id) as server, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 768}, accept_downloads=True)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(server.url)
        expect(page.locator(".frame")).to_have_count(5)
        page.locator("#preview-button").click()
        page.wait_for_function("() => document.querySelector('#video').readyState >= 2")
        assert page.locator("#video").evaluate("v => v.videoWidth") == 160
        page.locator("#video").evaluate("v => v.currentTime = 1.5")
        page.wait_for_function(
            "() => Math.abs(document.querySelector('#video').currentTime - 1.5) < .1"
        )
        assert not tool.saved_outputs()
        page.locator("#overlay-text").fill("A new caption")
        expect(page.locator("#live-overlay")).to_be_visible()
        expect(page.locator("#live-overlay")).to_have_text("A new caption")
        page.locator("#start-slider").evaluate(
            "el => { el.value = 1; el.dispatchEvent(new Event('input')); }"
        )
        page.locator("#settings-button").click()
        page.locator("#appearance").select_option("light")
        page.get_by_role("button", name="Save settings").click()
        expect(page.locator("#settings-dialog")).not_to_be_visible()
        expect(page.locator("#overlay-text")).to_have_value("A new caption")
        expect(page.locator("html")).to_have_attribute("data-theme", "light")
        page.locator("#export-button").click()
        expect(page.locator(".output-card")).to_have_count(1, timeout=20000)
        with page.expect_download() as event:
            page.locator(".output-card a").click()
        download = event.value
        download.save_as(tmp_path / "download.mp4")
        exports = tool.saved_outputs()
        from pathlib import Path

        assert (tmp_path / "download.mp4").read_bytes() == Path(exports[0]["artifact"]).read_bytes()
        page.get_by_role("button", name="Open in workspace").click()
        expect(page.locator(".frame")).to_have_count(5)
        expect(page.locator("#start")).to_have_value("1")
        expect(page.locator("#overlay-text")).to_have_value("A new caption")
        page.locator('[data-format="gif"]').click()
        page.locator("#export-button").click()
        expect(page.locator(".output-card")).to_have_count(2, timeout=20000)
        page.wait_for_function("() => document.querySelector('.output-card img').naturalWidth > 0")
        from PIL import Image

        gif = next(r for r in tool.saved_outputs() if r["plan"]["format"] == "gif")
        with Image.open(gif["artifact"]) as image:
            assert image.n_frames > 1
        page.locator("#workspace-tab").click()
        page.locator('[data-format="png"]').click()
        page.locator("#export-button").click()
        expect(page.locator(".output-card")).to_have_count(3, timeout=20000)
        assert not errors
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.evaluate("document.documentElement.scrollHeight <= innerHeight")
        browser.close()


def test_browser_distinct_sources_and_system_appearance(tool, fixture_video, tmp_path):
    import subprocess

    second_source = tmp_path / "yellow.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=yellow:s=96x64:r=10:d=1",
            "-c:v",
            "ffv1",
            str(second_source),
        ],
        check=True,
    )
    settings = tool.settings.model_dump()
    settings["source_roots"] = (*settings["source_roots"], str(tmp_path))
    tool.configure(settings, appearance="system")
    first = tool.render(
        tool.plan(str(fixture_video), 1, 2, format="png", overlay={"text": "First"})
    )
    second = tool.render(
        tool.plan(str(second_source), 0, 0.8, format="png", overlay={"text": "Second"})
    )
    with tool.dashboard() as server, sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1366, "height": 768}, color_scheme="dark")
        page.goto(server.url)
        expect(page.locator("#status-text")).to_have_text("Your collection. Your cut.")
        dark = page.locator("body").evaluate("el => getComputedStyle(el).backgroundColor")
        page.emulate_media(color_scheme="light")
        assert page.locator("body").evaluate("el => getComputedStyle(el).backgroundColor") != dark
        for receipt, text in [(first, "First"), (second, "Second"), (first, "First")]:
            page.locator("#saved-tab").click()
            card = page.locator(".output-card").filter(
                has=page.get_by_text(f"“{text}”", exact=True)
            )
            card.get_by_role("button", name="Open in workspace").click()
            expect(page.locator("#overlay-text")).to_have_value(text)
            expect(page.locator("#status-text")).to_have_text(
                "Ready to refine. Your earlier exports stay unchanged."
            )
            expect(page.locator("#image")).to_have_attribute(
                "src", "/media/export/" + receipt["artifact_id"]
            )
            assert page.locator("#source-title").text_content() in receipt["plan"]["source"]["path"]
            assert (
                page.locator("#image").evaluate("el => el.naturalWidth")
                == receipt["plan"]["source"]["width"]
            )
        assert len(tool.saved_outputs()) == 2
        browser.close()


def test_read_only_status_and_cancel_while_work_runs(tool, monkeypatch):
    import threading

    from outtake import OuttakeError

    entered = threading.Event()

    def ongoing(*, cancelled, **kwargs):
        entered.set()
        while not cancelled():
            time.sleep(0.01)
        raise OuttakeError("CANCELLED", "Work cancelled and cleaned up.", "Earlier exports remain.")

    monkeypatch.setattr(tool, "preview", ongoing)
    with tool.dashboard() as server:
        started = json.load(request(server, "/api/call", {"operation": "preview", "arguments": {}}))
        assert entered.wait(2)
        assert call(server, "preferences")["status"] == "complete"
        assert call(server, "saved_outputs")["result"] == []
        ack = json.load(request(server, "/api/cancel", {"job_id": started["job_id"]}))
        assert ack["acknowledged"]
        for _ in range(200):
            job = json.load(request(server, "/api/jobs/" + started["job_id"]))
            if job["status"] != "running":
                break
            time.sleep(0.01)
        assert job["result"]["status"] == "cancelled"


def test_browser_trim_selection_playback_and_export(tool, fixture_video):
    plan = tool.plan(str(fixture_video), 0, 2)
    tool.render(plan)
    with tool.dashboard(plan_id=plan.id) as server, sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        page.goto(server.url)
        expect(page.locator("#status-text")).to_have_text(
            "Ready to refine. Your earlier exports stay unchanged."
        )
        page.wait_for_function("() => document.querySelector('#video').readyState >= 2")
        calls = []
        page.on(
            "request",
            lambda request: calls.append(request.url) if "/api/call" in request.url else None,
        )
        page.locator('[data-format="gif"]').click()
        page.locator("#play-selection").click()
        page.wait_for_function("() => !document.querySelector('#video').paused")
        page.locator("#video").evaluate("v => v.pause()")
        assert not calls, "Trimming an available clip should not call the render API"
        page.locator('[data-format="mp4"]').click()
        seek = page.locator("#timeline-seek")
        box = seek.bounding_box()
        seek.click(position={"x": box["width"] * 0.75, "y": box["height"] / 2})
        page.wait_for_function(
            "() => Math.abs(document.querySelector('#video').currentTime - 1.5) < .03"
        )
        expect(page.locator("#playhead")).to_be_visible()
        expect(seek).to_have_attribute("aria-valuenow", "1.50")
        seek.press("ArrowLeft")
        expect(seek).to_have_attribute("aria-valuenow", "1.49")
        page.locator("#set-end").click()
        expect(page.locator("#end")).to_have_value("1.49")
        expect(page.locator("#start")).to_have_value("0")
        for boundary, value in [("start", 0.5), ("end", 1.2)]:
            page.locator(f"#{boundary}-slider").evaluate(
                "(el, value) => { el.value = value; el.dispatchEvent(new Event('input')); }", value
            )
        expect(page.locator("#trim-summary")).to_contain_text("0.70s kept")
        page.wait_for_function(
            "() => Math.abs(document.querySelector('#video').currentTime - 1.2) < .05"
        )
        page.locator("#play-selection").click()
        page.wait_for_function("() => !document.querySelector('#video').paused")
        page.wait_for_function("() => document.querySelector('#video').paused")
        assert abs(page.locator("#video").evaluate("v => v.currentTime") - 1.2) < 0.08
        page.locator("#loop-selection").click()
        expect(page.locator("#loop-selection")).to_have_attribute("aria-pressed", "true")
        page.locator("#video").evaluate(
            "v => { window.wraps = 0; let last = v.currentTime; v.addEventListener('timeupdate', () => { if (v.currentTime < last - .2) window.wraps++; last = v.currentTime; }); }"
        )
        page.locator("#play-selection").click()
        page.wait_for_function("() => window.wraps >= 3")
        assert not page.locator("#video").evaluate("v => v.paused")
        seek.click(position={"x": box["width"] * 0.4, "y": box["height"] / 2})
        page.wait_for_function("() => !document.querySelector('#video').paused")
        page.locator("#video").evaluate("v => v.pause()")
        page.locator("#expand-context").click()
        expect(page.locator("#status-text")).to_have_text(
            "More source context loaded. Your export selection is unchanged.", timeout=20000
        )
        expect(page.locator("#start")).to_have_value("0.50")
        expect(page.locator("#end")).to_have_value("1.20")
        expect(page.locator("#end-slider")).to_have_attribute("max", "3")
        page.locator("#export-button").click()
        expect(page.locator(".output-card")).to_have_count(2, timeout=20000)
        cut = next(r for r in tool.saved_outputs() if r["plan"]["start"] == 0.5)
        assert cut["plan"]["end"] == 1.2
        browser.close()
