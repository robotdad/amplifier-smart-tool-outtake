from urllib.parse import urljoin

from playwright.sync_api import expect, sync_playwright


def test_browser_named_timed_text_font_mobile_export_delete(tool, fixture_video):
    plan = tool.plan(str(fixture_video), 0, 2.5, captions_enabled=False)
    tool.render(plan)
    with tool.dashboard(plan_id=plan.id) as server, sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(server.url)
        expect(page.locator("#status-text")).to_have_text(
            "Ready to refine. Your earlier exports stay unchanged.", timeout=20000
        )
        expect(page.locator("#captions-summary")).to_have_attribute("aria-disabled", "true")
        page.locator("#captions-summary").click(force=True)
        assert not page.locator("#captions-section").evaluate("el => el.open")
        expect(page.locator("#text-editor")).not_to_be_visible()
        expect(page.locator("#trim-controls #add-cue")).to_be_visible()
        page.locator("#moment-title").fill("Sushi without paying 寿司")
        page.locator("#add-cue").click()
        page.locator("#overlay-text").fill("First speaker")
        page.locator("#cue-start").fill("0.2")
        page.locator("#cue-end").fill("0.9")
        font = tool.fonts()[-1]["id"]
        page.locator("#text-appearance summary").click()
        page.locator("#text-font").select_option(font)
        page.locator("#add-cue").click()
        page.locator("#overlay-text").fill("Second speaker")
        page.locator("#cue-start").fill("1.2")
        page.locator("#cue-end").fill("2.2")
        expect(page.locator(".cue-chip")).to_have_count(2)
        page.locator('[data-format="gif"]').click()
        expect(page.locator("#profile")).to_have_value("mobile")
        page.locator("#export-button").click()
        expect(page.locator(".output-card")).to_have_count(2, timeout=20000)
        result = next(r for r in tool.saved_outputs() if r["plan"]["format"] == "gif")
        assert result["plan"]["title"] == "Sushi without paying 寿司"
        assert len(result["plan"]["cues"]) == 2
        assert result["plan"]["cues"][0]["font"] == font
        assert result["frame_rate"] == "10"
        download = page.request.get(
            urljoin(server.url, f"/media/export/{result['artifact_id']}?download=1")
        )
        assert download.ok
        assert "filename*=UTF-8''" in download.headers["content-disposition"]
        assert len(download.body()) == result["bytes"]
        card = page.locator(".output-card").filter(
            has=page.get_by_role("heading", name="Sushi without paying 寿司")
        )
        card.get_by_role("button", name="Open", exact=True).click()
        expect(page.locator(".cue-chip")).to_have_count(2)
        page.locator(".cue-chip").first.click()
        expect(page.locator("#overlay-text")).to_have_value("First speaker")
        expect(page.locator("#status-text")).to_have_text(
            "Ready to refine. Your earlier exports stay unchanged.", timeout=20000
        )
        page.wait_for_function("() => activeJob === null && !cleanPreparing")
        page.locator("#saved-tab").click()
        page.on("dialog", lambda dialog: dialog.accept())
        card.get_by_role("button", name="Delete", exact=True).click()
        expect(page.locator(".output-card")).to_have_count(1)
        assert tool.get_plan(result["plan"]["id"]).title == "Sushi without paying 寿司"
        assert fixture_video.exists() and not errors
        browser.close()


def test_browser_original_captions_convert_switch_and_manual_text(bitmap_tool, bitmap_source):
    import shutil

    import pytest

    if not shutil.which("tesseract"):
        pytest.skip("Local OCR needs Tesseract")
    tool = bitmap_tool
    plan = tool.plan(str(bitmap_source), 0, 2)
    tool.render(plan)
    with tool.dashboard(plan_id=plan.id) as server, sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(server.url)
        expect(page.locator("#status-text")).to_have_text(
            "Ready to refine. Your earlier exports stay unchanged.", timeout=20000
        )
        expect(page.locator("#captions-summary")).to_have_attribute("aria-disabled", "false")
        page.locator("#captions-summary").click()
        expect(page.locator("#caption-mode")).to_have_value("original")
        page.locator("#convert-captions").click()
        expect(page.locator("#status-text")).to_have_text(
            "Converted with local OCR. Review the words and punctuation; source timing is preserved.",
            timeout=20000,
        )
        expect(page.locator("#caption-mode")).to_have_value("editable")
        expect(page.locator(".cue-chip")).to_have_count(1)
        page.locator(".cue-chip").click()
        expect(page.locator("#overlay-text")).to_have_value("HELLO")
        expect(page.locator("#cue-review")).to_contain_text("OCR")
        page.wait_for_function("() => activeJob === null && !cleanPreparing")
        page.locator("#overlay-text").fill("Edited subtitle")
        page.locator("#caption-mode").select_option("original")
        page.locator("#export-button").click()
        expect(page.locator(".output-card")).to_have_count(2, timeout=20000)
        result = next(r for r in tool.saved_outputs() if r["plan"]["cues"])
        assert result["plan"]["caption_mode"] == "original"
        assert result["plan"]["cues"][0]["text"] == "Edited subtitle"
        page.locator("#workspace-tab").click()
        page.locator("#caption-mode").select_option("editable")
        page.locator(".cue-chip").click()
        expect(page.locator("#overlay-text")).to_have_value("Edited subtitle")
        page.wait_for_function("() => activeJob === null && !cleanPreparing")
        page.locator("#captions-enabled").uncheck()
        page.locator("#add-cue").click()
        page.locator("#overlay-text").fill("Manual remains")
        page.locator("#export-button").click()
        expect(page.locator(".output-card")).to_have_count(3, timeout=20000)
        assert any(
            not r["plan"]["captions_enabled"]
            and any(c["text"] == "Manual remains" for c in r["plan"]["cues"])
            for r in tool.saved_outputs()
        )
        image = page.request.get(
            urljoin(server.url, f"/media/subtitle/{plan.caption_evidence_id}/0")
        )
        assert image.ok and image.headers["content-type"] == "image/png"
        assert not errors
        browser.close()


def test_play_waits_for_replacement_preview_and_trim_seek(tool, fixture_video, monkeypatch):
    import threading

    plan = tool.plan(
        str(fixture_video), 0, 2.8, overlay={"text": "Caption"}, captions_enabled=False
    )
    tool.render(plan)
    release = threading.Event()
    started = threading.Event()
    original = tool.preview

    def delayed_preview(*args, **kwargs):
        started.set()
        assert release.wait(15), "Test never released preview generation"
        return original(*args, **kwargs)

    monkeypatch.setattr(tool, "preview", delayed_preview)
    with tool.dashboard(plan_id=plan.id) as server, sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(server.url)
        expect(page.locator("#status-text")).to_have_text(
            "Ready to refine. Your earlier exports stay unchanged.", timeout=20000
        )
        page.locator("#start-slider").fill("0.83")
        assert started.wait(5)
        page.locator("#play-selection").click()
        expect(page.locator("#play-selection")).to_have_text("Preparing…")
        assert page.locator("#video").evaluate("v => v.paused")
        release.set()
        expect(page.locator("#play-selection")).to_have_text("Ⅱ Pause", timeout=20000)
        page.wait_for_function("() => document.querySelector('#video').currentTime > 1.1", timeout=5000)
        assert not page.locator("#video").evaluate("v => v.paused")
        assert not page.locator("#error").is_visible()
        page.locator("#play-selection").click()
        page.locator("#start-slider").fill("1.37")
        page.locator("#play-selection").click()
        page.wait_for_function("() => document.querySelector('#video').currentTime > 1.6", timeout=5000)
        assert not page.locator("#error").is_visible()
        browser.close()
