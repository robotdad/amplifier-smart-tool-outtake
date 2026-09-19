"""Provider-free MCP Apps checks through the official SDK and an AppBridge host."""

# fmt: off

import asyncio
import re
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("mcp")
pytest.importorskip("playwright")
from fixtures.mcp_seed import seed_finding_review, seed_plan_review
from mcp import Client
from playwright.async_api import async_playwright, expect

from outtake.mcp_adapter import create_server

ROOT = Path(__file__).parents[1]


def _native_html():
    """Build the native-only comparison document from the dashboard sources."""

    html = (ROOT / "src" / "outtake" / "static" / "index.html").read_text()
    css = (ROOT / "src" / "outtake" / "static" / "app.css").read_text()
    html = html.replace(
        '<link rel="stylesheet" href="/app.css" />',
        f"<style>{css}</style>",
    )
    return re.sub(r'<script src="/app\.js" defer></script>', "", html)


def _host_bundle():
    node_modules = ROOT / "mcp-app" / "node_modules"
    resource = ROOT / "src" / "outtake" / "resources" / "mcp_app.html"
    if not node_modules.exists():
        pytest.skip("Run npm ci --prefix mcp-app for the independent AppBridge fixture.")
    if not resource.is_file():
        pytest.fail("Build mcp-app before running the browser tests.")
    return subprocess.run(
        [
            str(node_modules / ".bin" / "esbuild"),
            str(ROOT / "mcp-app" / "test-host.js"),
            "--bundle",
            "--format=iife",
            "--log-level=error",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _wire(result):
    return result.model_dump(by_alias=True, exclude_none=True)


def _data(result):
    data = _wire(result)
    if isinstance(data.get("structuredContent"), dict):
        data = data["structuredContent"]
    while (
        isinstance(data, dict)
        and isinstance(data.get("result"), dict)
        and not any(
            key in data for key in ("review_id", "plan", "displayed_plan", "view")
        )
    ):
        data = data["result"]
    return data


async def _app_html(client):
    listed = await client.list_resources()
    resource = next(
        (item for item in listed.resources if str(item.uri) == "ui://outtake/review"),
        None,
    )
    assert resource is not None
    assert resource.mime_type == "text/html;profile=mcp-app"
    loaded = await client.read_resource("ui://outtake/review")
    content = next(
        (item for item in loaded.contents if getattr(item, "text", None)),
        None,
    )
    assert content is not None
    return content.text


async def _mount(page, html, initial, *, theme="dark", resources=True):
    await page.evaluate(
        "([html,result,theme,resources]) => mountOuttake(html,result,{theme,resources})",
        [html, _wire(initial), theme, resources],
    )
    return page.frame_locator("#app")


def test_mcp_app_retained_video_drafts_apply_media_and_reopen(
    tmp_path, tool, fixture_video
):
    """A real retained export is reviewed, downloaded, revised, and reopened."""

    script = _host_bundle()

    async def run():
        seeded = seed_plan_review(tool, fixture_video)
        async with Client(
            create_server(tool.settings, [seeded["review_id"]])
        ) as client, async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            page = await browser.new_page(
                viewport={"width": 1040, "height": 1300}
            )
            errors = []
            calls = []
            reads = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            async def host_call(arguments):
                calls.append(arguments)
                result = await client.call_tool(
                    arguments["name"], arguments.get("arguments", {})
                )
                return _wire(result)

            async def host_read(arguments):
                reads.append(arguments)
                return _wire(await client.read_resource(arguments["uri"]))

            await page.expose_function("hostCall", host_call)
            await page.expose_function("hostRead", host_read)
            await page.goto("about:blank")
            await page.add_script_tag(content=script)
            initial = await client.call_tool(
                "outtake_review", {"review_id": seeded["review_id"]}
            )
            html = await _app_html(client)
            frame = await _mount(page, html, initial)
            await expect(frame.locator("#status-text")).to_have_text(
                "Attached to retained review. No work was started.",
                timeout=15000,
            )
            await expect(frame.locator("#mcp-review-id")).to_have_text(
                seeded["review_id"]
            )
            await expect(frame.locator("#video")).to_be_visible()
            await expect(frame.locator("#video")).to_have_js_property(
                "videoWidth", 160
            )
            original_media = Path(seeded["receipt"]["artifact"]).read_bytes()
            assert await frame.locator("#video").evaluate("video => video.duration") == pytest.approx(
                1.2, abs=0.15
            )
            assert len(reads) >= 1
            assert await frame.locator("html").get_attribute("data-theme") == "dark"

            # Workspace playback stays native; retained-output downloads live
            # on the Saved Outputs cards, where the native icon action is tested
            # below rather than adding a second workspace control.
            assert await frame.locator("#download").count() == 0
            assert "http://" not in (await frame.locator("body").inner_text())
            assert "https://" not in (await frame.locator("body").inner_text())

            # Raw draft persistence is separate from applying a plan.
            await frame.locator("#moment-title").fill("Unapplied typed title")
            await expect(frame.locator("#dirty-label")).to_contain_text(
                "Draft saved"
            )
            retained = tool.review_snapshot(seeded["review_id"])
            assert retained["workspace"]["plan"]["title"] == seeded["plan"].title
            assert retained["draft"]["value"]["title"] == "Unapplied typed title"

            await frame.locator("#start-slider").fill("0.2")
            await frame.locator("#frame").fill("0.6")
            await frame.locator("#moment-title").fill("Applied green handoff")
            await expect(frame.locator("#dirty-label")).to_contain_text("Draft saved")
            applied = _data(
                await client.call_tool(
                    "outtake_apply_changes",
                    {
                        "review_id": seeded["review_id"],
                        "plan_id": seeded["plan"].id,
                        "changes": {"title": "Applied green handoff"},
                        "request_id": "browser-agent-apply",
                    },
                )
            )
            revised = applied["plan"]
            assert revised["id"] != seeded["plan"].id
            assert revised["title"] == "Applied green handoff"
            assert Path(seeded["receipt"]["artifact"]).read_bytes() == original_media
            before_navigation = _data(
                await client.call_tool("outtake_review", {"review_id": seeded["review_id"]})
            )
            navigation = _data(
                await client.call_tool(
                    "outtake_navigate",
                    {
                        "review_id": seeded["review_id"],
                        "view": {"plan_id": revised["id"]},
                        "expected_version": before_navigation["view_version"],
                        "request_id": "browser-agent-apply-navigation",
                    },
                )
            )
            assert navigation["view"]["plan_id"] == revised["id"]
            await page.evaluate(
                """reviewId => window.outtakeBridge.sendToolResult({
                    structuredContent: {review_id: reviewId},
                    content: [{type: "text", text: JSON.stringify({review_id: reviewId})}]
                })""",
                seeded["review_id"],
            )
            await expect(frame.locator("#source-title")).to_have_text(
                "Applied green handoff", timeout=15000
            )

            admits_before_reopen = len(
                [call for call in calls if call["name"] == "outtake_admit"]
            )
            initial_again = await client.call_tool(
                "outtake_review", {"review_id": seeded["review_id"]}
            )
            frame = await _mount(
                page, html, initial_again, theme="light", resources=True
            )
            await expect(frame.locator("#mcp-review-id")).to_have_text(
                seeded["review_id"], timeout=15000
            )
            await expect(frame.locator("#moment-title")).to_have_value(
                "Applied green handoff"
            )
            assert len(
                [call for call in calls if call["name"] == "outtake_admit"]
            ) == admits_before_reopen
            assert await frame.locator("html").get_attribute("data-theme") == "light"

            await page.set_viewport_size({"width": 430, "height": 1000})
            assert await frame.locator("body").evaluate(
                "node => node.scrollWidth <= window.innerWidth"
            )
            assert not errors, errors
            await page.screenshot(
                path=str(tmp_path / "outtake-mcp-review-narrow.png"),
                full_page=True,
            )
            await browser.close()

    asyncio.run(run())


def test_mcp_app_saved_outputs_list_open_retry_and_refresh(tool, fixture_video):
    """Saved cards use scoped resources, preserve independent drafts, and refresh after export."""

    script = _host_bundle()

    async def run():
        first = seed_plan_review(tool, fixture_video, title="Green saved output")
        second = seed_plan_review(
            tool, fixture_video, start=1.0, end=2.0, title="Blue saved output"
        )
        async with Client(
            create_server(tool.settings, [first["review_id"]], allow_saved_outputs=True)
        ) as client, async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            page = await browser.new_page(
                viewport={"width": 1040, "height": 1300},
                accept_downloads=True,
            )
            calls, lose_open = [], {"value": True}

            async def host_call(arguments):
                calls.append(arguments)
                result = await client.call_tool(
                    arguments["name"], arguments.get("arguments", {})
                )
                if arguments["name"] == "outtake_open_saved_output" and lose_open["value"]:
                    lose_open["value"] = False
                    raise RuntimeError("simulated lost open response")
                return _wire(result)

            async def host_read(arguments):
                return _wire(await client.read_resource(arguments["uri"]))

            await page.expose_function("hostCall", host_call)
            await page.expose_function("hostRead", host_read)
            await page.goto("about:blank")
            await page.add_script_tag(content=script)
            initial = await client.call_tool(
                "outtake_review", {"review_id": first["review_id"]}
            )
            frame = await _mount(page, await _app_html(client), initial)
            await expect(frame.locator("#mcp-review-id")).to_have_text(
                first["review_id"], timeout=15000
            )
            await frame.locator("#moment-title").fill("First raw saved draft")
            await expect(frame.locator("#dirty-label")).to_contain_text("Draft saved")

            await frame.locator("#saved-tab").click()
            await expect(frame.locator("#saved-grid article.output-card")).to_have_count(2)
            blue = frame.locator(
                "#saved-grid article.output-card", has_text="Blue saved output"
            )
            green = frame.locator(
                "#saved-grid article.output-card", has_text="Green saved output"
            )
            await expect(blue.locator("video")).to_have_attribute("src", re.compile("^blob:"))
            await expect(green.locator("video")).to_have_attribute("src", re.compile("^blob:"))
            download_path = "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"
            delete_path = "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"
            for card in (green, blue):
                download = card.locator("a.icon-action[aria-label='Download']")
                remove = card.locator("button.icon-action[aria-label='Delete']")
                await expect(download).to_have_count(1)
                await expect(download).to_have_attribute("title", "Download")
                await expect(remove).to_have_count(1)
                await expect(remove).to_have_attribute("title", "Delete")
                assert await download.locator("svg path").get_attribute("d") == download_path
                assert await remove.locator("svg path").get_attribute("d") == delete_path
                assert "Download" not in await card.inner_text()
                assert "Delete" not in await card.inner_text()

            async with page.expect_download() as download_event:
                await blue.locator("a[aria-label='Download']").click()
            downloaded = await download_event.value
            downloaded_path = await downloaded.path()
            assert downloaded_path is not None
            assert Path(downloaded_path).read_bytes() == Path(
                second["receipt"]["artifact"]
            ).read_bytes()

            # The server accepted the first request but its response was lost. The
            # retry must reuse its request identity and the canonical export review.
            await blue.get_by_role("button", name="Open").click()
            await expect(frame.locator("#status-text")).to_contain_text(
                "lost open response", timeout=15000
            )
            await blue.get_by_role("button", name="Open").click()
            await expect(frame.locator("#moment-title")).to_have_value("Blue saved output")
            await frame.locator("#moment-title").fill("Second raw saved draft")
            await expect(frame.locator("#dirty-label")).to_contain_text("Draft saved")

            await frame.locator("#saved-tab").click()
            green = frame.locator(
                "#saved-grid article.output-card", has_text="Green saved output"
            )
            await green.get_by_role("button", name="Open").click()
            await expect(frame.locator("#moment-title")).to_have_value(
                "First raw saved draft"
            )
            blue_calls = [
                item
                for item in calls
                if item["name"] == "outtake_open_saved_output"
                and item["arguments"]["artifact_id"] == second["receipt"]["artifact_id"]
            ]
            assert len(blue_calls) == 2
            assert blue_calls[0]["arguments"]["request_id"] == blue_calls[1]["arguments"]["request_id"]

            await frame.locator("#export-button").click()
            await expect(frame.locator("#render-state")).to_contain_text(
                "Ready", timeout=30000
            )
            await expect(frame.locator("#saved-count")).to_have_text("3", timeout=15000)
            assert not any(
                item["name"] in {"outtake_find", "outtake_make"} for item in calls
            )

            # Delete only the newly generated disposable fixture output, and
            # verify the native confirmation path and scoped removal.
            await frame.locator("#saved-tab").click()
            await expect(frame.locator("#saved-grid article.output-card")).to_have_count(3)
            seeded_ids = {
                first["receipt"]["artifact_id"],
                second["receipt"]["artifact_id"],
            }
            disposable = next(
                receipt
                for receipt in tool.saved_outputs()
                if receipt["artifact_id"] not in seeded_ids
            )
            disposable_card = frame.locator(
                f"#saved-grid article.output-card[data-artifact-id='{disposable['artifact_id']}']"
            )
            # AppBridge's sandbox intentionally omits allow-modals. Stub the
            # native confirmation in the disposable fixture so the guard is
            # exercised without deleting a real retained output.
            await frame.locator("body").evaluate(
                """body => {
                    window.outtakeConfirmations = [];
                    window.confirm = message => {
                        window.outtakeConfirmations.push(message);
                        return true;
                    };
                }"""
            )
            await disposable_card.locator("button[aria-label='Delete']").click()
            await expect(frame.locator("#saved-count")).to_have_text("2", timeout=15000)
            confirmations = await frame.locator("body").evaluate(
                "body => window.outtakeConfirmations"
            )
            assert confirmations and "Delete" in confirmations[0]
            assert disposable["artifact_id"] not in {
                receipt["artifact_id"] for receipt in tool.saved_outputs()
            }
            await browser.close()

    asyncio.run(run())

# fmt: on


def test_mcp_app_navigation_flushes_exact_old_target_draft(tool, fixture_video):
    """Navigation waits for the old target while preserving newer typing."""

    script = _host_bundle()

    async def run():
        first = seed_plan_review(tool, fixture_video, title="First target")
        second = seed_plan_review(tool, fixture_video, start=1.1, end=2.4, title="Second target")
        delayed = {"active": True}
        save_started = asyncio.Event()
        release_save = asyncio.Event()
        calls = []

        async with (
            Client(
                create_server(tool.settings, [first["review_id"], second["review_id"]])
            ) as client,
            async_playwright() as playwright,
        ):
            browser = await playwright.chromium.launch()
            page = await browser.new_page(viewport={"width": 980, "height": 1200})

            async def host_call(arguments):
                calls.append(arguments)
                if arguments["name"] == "outtake_save_draft" and delayed["active"]:
                    delayed["active"] = False
                    save_started.set()
                    await release_save.wait()
                return _wire(
                    await client.call_tool(arguments["name"], arguments.get("arguments", {}))
                )

            async def host_read(arguments):
                return _wire(await client.read_resource(arguments["uri"]))

            await page.expose_function("hostCall", host_call)
            await page.expose_function("hostRead", host_read)
            await page.goto("about:blank")
            await page.add_script_tag(content=script)
            initial = await client.call_tool("outtake_review", {"review_id": first["review_id"]})
            html = await _app_html(client)
            frame = await _mount(page, html, initial)
            await expect(frame.locator("#mcp-review-id")).to_have_text(
                first["review_id"], timeout=15000
            )

            await frame.locator("#moment-title").fill("First draft before move")
            await asyncio.wait_for(save_started.wait(), 5)
            # This edit happens while the first save is in flight. Navigation
            # must flush this newer value to the first review, not the second.
            await frame.locator("#moment-title").fill("Latest first draft")
            await page.evaluate(
                """reviewId => {
                    window.pendingNavigation =
                        window.outtakeBridge.sendToolResult({
                            structuredContent: {review_id: reviewId},
                            content: [{type: "text", text: JSON.stringify({review_id: reviewId})}]
                        });
                }""",
                second["review_id"],
            )
            await asyncio.sleep(0.05)
            release_save.set()
            await page.evaluate("() => window.pendingNavigation")
            await expect(frame.locator("#mcp-review-id")).to_have_text(
                second["review_id"], timeout=15000
            )

            old_snapshot = tool.review_snapshot(first["review_id"])
            assert old_snapshot["draft"]["value"]["title"] == "Latest first draft"
            save_calls = [call for call in calls if call["name"] == "outtake_save_draft"]
            assert len(save_calls) >= 2
            assert all(
                call["arguments"]["review_id"] == first["review_id"] for call in save_calls[:2]
            )
            assert save_calls[0]["arguments"]["base_plan_id"] == first["plan"].id
            assert save_calls[1]["arguments"]["base_plan_id"] == first["plan"].id
            assert save_calls[1]["arguments"]["draft"]["title"] == "Latest first draft"
            assert save_calls[0]["arguments"]["expected_version"] == 0
            assert save_calls[1]["arguments"]["expected_version"] == 1
            await browser.close()

    asyncio.run(run())


def test_mcp_app_lost_admission_reuses_original_request_and_resource_failure_clears(
    tool, fixture_video
):
    """Unknown admission results are reconciled; failed media cannot stay active."""

    script = _host_bundle()

    async def run():
        first = seed_plan_review(tool, fixture_video, title="Request identity")
        second = seed_plan_review(tool, fixture_video, start=1.2, end=2.5, title="Failure target")
        lose_once = {"admit": True}
        fail_reads_for = {second["review_id"]}
        calls = []
        reads = []

        async with (
            Client(
                create_server(tool.settings, [first["review_id"], second["review_id"]])
            ) as client,
            async_playwright() as playwright,
        ):
            browser = await playwright.chromium.launch()
            page = await browser.new_page(viewport={"width": 1000, "height": 1250})

            async def host_call(arguments):
                calls.append(arguments)
                result = _wire(
                    await client.call_tool(arguments["name"], arguments.get("arguments", {}))
                )
                if arguments["name"] == "outtake_admit" and lose_once["admit"]:
                    lose_once["admit"] = False
                    raise RuntimeError("accepted admission acknowledgement was lost")
                return result

            async def host_read(arguments):
                reads.append(arguments)
                if any(identity in arguments["uri"] for identity in fail_reads_for):
                    raise RuntimeError("fixture resource failure after descriptor")
                return _wire(await client.read_resource(arguments["uri"]))

            await page.expose_function("hostCall", host_call)
            await page.expose_function("hostRead", host_read)
            await page.goto("about:blank")
            await page.add_script_tag(content=script)
            initial = await client.call_tool("outtake_review", {"review_id": first["review_id"]})
            html = await _app_html(client)
            frame = await _mount(page, html, initial)
            await expect(frame.locator("#mcp-review-id")).to_have_text(
                first["review_id"], timeout=15000
            )

            await frame.locator("#export-button").click()
            await expect(frame.locator("#status[data-state='error']")).to_contain_text(
                "response is uncertain"
            )
            first_admit = next(call for call in calls if call["name"] == "outtake_admit")
            await frame.locator("#render-check").click()
            await expect(frame.locator("#render-state")).to_contain_text("Ready", timeout=20000)
            admit_calls = [call for call in calls if call["name"] == "outtake_admit"]
            assert len(admit_calls) == 2
            assert admit_calls[1]["arguments"] == first_admit["arguments"]
            assert (
                admit_calls[1]["arguments"]["request_id"] == first_admit["arguments"]["request_id"]
            )
            assert len(tool.saved_outputs()) >= 2

            # Host navigation to a different retained target causes the old
            # media URL to be cleared before the failed resource read.
            await page.evaluate(
                """reviewId => window.outtakeBridge.sendToolResult({
                    structuredContent: {review_id: reviewId},
                    content: [{type: "text", text: JSON.stringify({review_id: reviewId})}]
                })""",
                second["review_id"],
            )
            failure_frame = page.frame_locator("#app")
            await expect(failure_frame.locator("#mcp-review-id")).to_have_text(
                second["review_id"], timeout=15000
            )
            await expect(failure_frame.locator("#status[data-state='error']")).to_be_visible()
            await expect(failure_frame.locator("#video")).to_be_hidden()
            await expect(failure_frame.locator("#image")).to_be_hidden()
            assert await failure_frame.locator("#video").get_attribute("src") is None
            assert await failure_frame.locator("#image").get_attribute("src") is None
            assert await failure_frame.locator("#download").count() == 0
            assert reads

            # Reopen without resource reads: the server capability is honest
            # and the app does not substitute a dashboard URL.
            initial_again = await client.call_tool(
                "outtake_review", {"review_id": first["review_id"]}
            )
            frame = await _mount(page, html, initial_again, resources=False)
            await expect(frame.locator("#status[data-state='error']")).to_contain_text(
                "does not support MCP resource reads", timeout=15000
            )
            await expect(frame.locator("#video")).to_be_hidden()
            assert not any("http://" in str(call) or "https://" in str(call) for call in calls)
            await browser.close()

    asyncio.run(run())


def test_mcp_app_candidate_and_evidence_review_is_not_generic_json(tool, fixture_video):
    """A retained finding shows evidence and keeps selection explicit."""

    script = _host_bundle()

    async def run():
        seeded = seed_finding_review(tool, fixture_video)
        async with (
            Client(create_server(tool.settings, [seeded["review_id"]])) as client,
            async_playwright() as playwright,
        ):
            browser = await playwright.chromium.launch()
            page = await browser.new_page(viewport={"width": 980, "height": 1250})
            calls = []
            reads = []

            async def host_call(arguments):
                calls.append(arguments)
                return _wire(
                    await client.call_tool(arguments["name"], arguments.get("arguments", {}))
                )

            async def host_read(arguments):
                reads.append(arguments)
                return _wire(await client.read_resource(arguments["uri"]))

            await page.expose_function("hostCall", host_call)
            await page.expose_function("hostRead", host_read)
            await page.goto("about:blank")
            await page.add_script_tag(content=script)
            initial = await client.call_tool("outtake_review", {"review_id": seeded["review_id"]})
            html = await _app_html(client)
            frame = await _mount(page, html, initial)
            await expect(frame.locator("#moments-list .moment")).to_have_count(1, timeout=15000)
            await expect(frame.locator("#request-title")).to_contain_text("green-to-blue")
            body = await frame.locator("body").inner_text()
            assert str(fixture_video) not in body
            assert "source_id" not in body

            await frame.locator("button[data-evidence-id]").first.click()
            await expect(frame.locator("#image")).to_be_visible(timeout=15000)
            assert reads
            await frame.get_by_role("button", name="Select candidate").click()
            await expect(frame.locator("#edit-controls")).to_be_visible(timeout=15000)
            selection = next(call for call in calls if call["name"] == "outtake_select_candidate")
            assert selection["arguments"]["review_id"] == seeded["review_id"]
            assert selection["arguments"]["finding_id"] == seeded["finding"]["id"]
            assert selection["arguments"]["candidate_id"] == seeded["candidate_id"]
            assert not any(
                call["name"] in {"outtake_admit", "outtake_save_draft"} for call in calls
            )
            await browser.close()

    asyncio.run(run())


def test_mcp_app_keeps_displayed_revision_until_explicit_navigation(tmp_path, tool, fixture_video):
    """Workspace-head changes do not silently replace persisted review focus."""

    script = _host_bundle()

    async def run():
        seeded = seed_plan_review(tool, fixture_video, title="Original shown plan")
        async with (
            Client(create_server(tool.settings, [seeded["review_id"]])) as client,
            async_playwright() as playwright,
        ):
            browser = await playwright.chromium.launch()
            page = await browser.new_page(viewport={"width": 1000, "height": 1300})
            calls = []

            async def host_call(arguments):
                calls.append(arguments)
                return _wire(
                    await client.call_tool(arguments["name"], arguments.get("arguments", {}))
                )

            async def host_read(arguments):
                return _wire(await client.read_resource(arguments["uri"]))

            await page.expose_function("hostCall", host_call)
            await page.expose_function("hostRead", host_read)
            await page.goto("about:blank")
            await page.add_script_tag(content=script)
            initial = await client.call_tool("outtake_review", {"review_id": seeded["review_id"]})
            html = await _app_html(client)
            frame = await _mount(page, html, initial)
            await expect(frame.locator("#source-title")).to_have_text(
                "Original shown plan", timeout=15000
            )
            for selector in (
                "#mcp-review-controls",
                "#revision-select",
                "#adopt-head",
                "#mcp-refresh",
            ):
                assert await frame.locator(selector).count() == 0, selector
            await expect(frame.locator("#revision-label")).to_have_text("Revision 1")

            await frame.locator("#moment-title").fill("Original retained draft")
            await expect(frame.locator("#dirty-label")).to_contain_text("Draft saved")

            advanced = await client.call_tool(
                "outtake_apply_changes",
                {
                    "review_id": seeded["review_id"],
                    "plan_id": seeded["plan"].id,
                    "changes": {"title": "Agent advanced head"},
                    "request_id": "agent-head-advance",
                },
            )
            advanced_data = _data(advanced)
            new_plan = advanced_data["plan"]
            new_plan_id = new_plan["id"]
            new_plan_revision = new_plan["revision"]
            assert new_plan_id != seeded["plan"].id
            before_navigation = _data(
                await client.call_tool("outtake_review", {"review_id": seeded["review_id"]})
            )
            assert before_navigation["displayed_plan"]["id"] == seeded["plan"].id
            assert before_navigation["head_plan_id"] == new_plan_id
            assert before_navigation["draft"]["value"]["title"] == "Original retained draft"

            # Refresh is a public retained-review read, not a UI-specific
            # adoption control. Sending the same host result back through the
            # official bridge must keep the displayed revision and draft.
            await page.evaluate(
                """reviewId => window.outtakeBridge.sendToolResult({
                    structuredContent: {review_id: reviewId},
                    content: [{type: "text", text: JSON.stringify({review_id: reviewId})}]
                })""",
                seeded["review_id"],
            )
            await expect(frame.locator("#revision-label")).to_have_text("Revision 1")
            await expect(frame.locator("#moment-title")).to_have_value("Original retained draft")
            assert not any(call["name"] == "outtake_navigate" for call in calls)

            navigation = _data(
                await client.call_tool(
                    "outtake_navigate",
                    {
                        "review_id": seeded["review_id"],
                        "view": {"plan_id": new_plan_id, "playhead": 0.85},
                        "expected_version": before_navigation["view_version"],
                        "request_id": "agent-adopt-head",
                    },
                )
            )
            assert navigation["view"]["plan_id"] == new_plan_id

            await page.evaluate(
                """reviewId => window.outtakeBridge.sendToolResult({
                    structuredContent: {review_id: reviewId},
                    content: [{type: "text", text: JSON.stringify({review_id: reviewId})}]
                })""",
                seeded["review_id"],
            )
            await expect(frame.locator("#revision-label")).to_have_text(
                f"Revision {new_plan_revision}", timeout=15000
            )
            await expect(frame.locator("#source-title")).to_have_text("Agent advanced head")
            assert tool.review_snapshot(seeded["review_id"])["view"]["playhead"] == pytest.approx(
                0.85
            )
            assert float(
                await frame.locator("#timeline-seek").get_attribute("aria-valuenow")
            ) <= float(await frame.locator("#timeline-seek").get_attribute("aria-valuemax"))

            await frame.locator("#moment-title").fill("New revision retained draft")
            await expect(frame.locator("#dirty-label")).to_contain_text("Draft saved")
            saved_head_draft = tool.review_snapshot(seeded["review_id"])
            assert (
                saved_head_draft["draft"]["base_plan_id"] == new_plan_id
                and saved_head_draft["draft"]["value"]["title"] == "New revision retained draft"
            )
            await frame.locator("#timeline-seek").evaluate(
                """track => {
                    const box = track.getBoundingClientRect();
                    const fraction = (1.05 - 0.4) / (1.6 - 0.4);
                    track.dispatchEvent(new MouseEvent('click', {
                        bubbles: true,
                        clientX: box.left + box.width * fraction,
                        clientY: box.top + box.height / 2,
                    }));
                }"""
            )
            for _ in range(30):
                if tool.review_snapshot(seeded["review_id"])["view"].get(
                    "playhead"
                ) == pytest.approx(1.05, abs=0.02):
                    break
                await asyncio.sleep(0.05)
            else:
                pytest.fail("Native timeline click did not persist review playhead")
            assert float(
                await frame.locator("#timeline-seek").get_attribute("aria-valuenow")
            ) <= float(await frame.locator("#timeline-seek").get_attribute("aria-valuemax"))

            reopened = await client.call_tool("outtake_review", {"review_id": seeded["review_id"]})
            frame = await _mount(page, html, reopened, theme="light")
            await expect(frame.locator("#revision-label")).to_have_text(
                f"Revision {new_plan_revision}", timeout=15000
            )
            await expect(frame.locator("#moment-title")).to_have_value(
                "New revision retained draft"
            )
            assert tool.review_snapshot(seeded["review_id"])["view"]["playhead"] == pytest.approx(
                1.05, abs=0.02
            )
            assert float(
                await frame.locator("#timeline-seek").get_attribute("aria-valuenow")
            ) <= float(await frame.locator("#timeline-seek").get_attribute("aria-valuemax"))
            await expect(frame.locator("html")).to_have_attribute("data-theme", "light")
            await page.screenshot(
                path=str(tmp_path / "outtake-semantic-revision.png"),
                full_page=True,
            )
            await browser.close()

    asyncio.run(run())


def test_mcp_app_lost_apply_and_navigation_retry_exact_ids_once(tool, fixture_video):
    """Lost mutation acknowledgements are retried exactly without duplicate revisions."""

    script = _host_bundle()

    async def run():
        seeded = seed_plan_review(tool, fixture_video, title="Retry base")
        calls = []
        async with (
            Client(create_server(tool.settings, [seeded["review_id"]])) as client,
            async_playwright() as playwright,
        ):
            browser = await playwright.chromium.launch()
            page = await browser.new_page(viewport={"width": 1000, "height": 1300})

            async def host_call(arguments):
                calls.append(arguments)
                return _wire(
                    await client.call_tool(arguments["name"], arguments.get("arguments", {}))
                )

            async def host_read(arguments):
                return _wire(await client.read_resource(arguments["uri"]))

            await page.expose_function("hostCall", host_call)
            await page.expose_function("hostRead", host_read)
            await page.goto("about:blank")
            await page.add_script_tag(content=script)
            initial = await client.call_tool("outtake_review", {"review_id": seeded["review_id"]})
            initial_wire = _data(initial)
            html = await _app_html(client)
            frame = await _mount(page, html, initial)
            await expect(frame.locator("#source-title")).to_have_text("Retry base", timeout=15000)

            # The App has no extra apply/navigation toolbar. Exercise the same
            # retained public tools directly, replaying each exact request after
            # intentionally ignoring its first acknowledgement.
            apply_arguments = {
                "review_id": seeded["review_id"],
                "plan_id": seeded["plan"].id,
                "changes": {"title": "Exactly once revision"},
                "request_id": "lost-apply-request",
            }
            calls.extend(
                [
                    {"name": "outtake_apply_changes", "arguments": apply_arguments},
                    {"name": "outtake_apply_changes", "arguments": apply_arguments},
                ]
            )
            first_apply = _data(await client.call_tool("outtake_apply_changes", apply_arguments))
            second_apply = _data(await client.call_tool("outtake_apply_changes", apply_arguments))
            assert first_apply == second_apply
            revised = second_apply["plan"]
            assert revised["title"] == "Exactly once revision"

            before_navigation = _data(
                await client.call_tool("outtake_review", {"review_id": seeded["review_id"]})
            )
            navigation_arguments = {
                "review_id": seeded["review_id"],
                "view": {"plan_id": revised["id"]},
                "expected_version": before_navigation["view_version"],
                "request_id": "lost-navigation-request",
            }
            calls.extend(
                [
                    {"name": "outtake_navigate", "arguments": navigation_arguments},
                    {"name": "outtake_navigate", "arguments": navigation_arguments},
                ]
            )
            first_navigation = _data(
                await client.call_tool("outtake_navigate", navigation_arguments)
            )
            second_navigation = _data(
                await client.call_tool("outtake_navigate", navigation_arguments)
            )
            assert first_navigation == second_navigation
            assert second_navigation["view"]["plan_id"] == revised["id"]
            apply_calls = [call for call in calls if call["name"] == "outtake_apply_changes"]
            navigation_calls = [call for call in calls if call["name"] == "outtake_navigate"]
            assert len(apply_calls) == 2
            assert apply_calls[0]["arguments"] == apply_calls[1]["arguments"]
            assert apply_calls[0]["arguments"]["request_id"]
            assert len(navigation_calls) == 2
            assert navigation_calls[0]["arguments"] == navigation_calls[1]["arguments"]
            assert navigation_calls[0]["arguments"]["request_id"]

            await page.evaluate(
                """reviewId => window.outtakeBridge.sendToolResult({
                    structuredContent: {review_id: reviewId},
                    content: [{type: "text", text: JSON.stringify({review_id: reviewId})}]
                })""",
                seeded["review_id"],
            )
            await expect(frame.locator("#source-title")).to_have_text(
                "Exactly once revision", timeout=15000
            )

            final_snapshot = _data(
                await client.call_tool("outtake_review", {"review_id": seeded["review_id"]})
            )
            assert final_snapshot["displayed_plan"]["title"] == "Exactly once revision"
            assert final_snapshot["view_version"] == initial_wire["view_version"] + 1
            assert final_snapshot["head_plan_id"] == final_snapshot["displayed_plan"]["id"]
            await browser.close()

    asyncio.run(run())


def test_mcp_app_uses_native_layout_and_reacts_to_runtime_theme(tool, fixture_video):
    """The transport wrapper keeps native boxes/controls and follows host theme changes."""

    script = _host_bundle()

    async def run():
        seeded = seed_plan_review(tool, fixture_video)
        async with (
            Client(create_server(tool.settings, [seeded["review_id"]])) as client,
            async_playwright() as playwright,
        ):
            browser = await playwright.chromium.launch()
            page = await browser.new_page(viewport={"width": 1180, "height": 900})
            native = await browser.new_page(viewport={"width": 1180, "height": 900})
            calls = []

            async def host_call(arguments):
                calls.append(arguments)
                return _wire(
                    await client.call_tool(arguments["name"], arguments.get("arguments", {}))
                )

            async def host_read(arguments):
                return _wire(await client.read_resource(arguments["uri"]))

            await page.expose_function("hostCall", host_call)
            await page.expose_function("hostRead", host_read)
            await page.goto("about:blank")
            await page.add_script_tag(content=script)
            initial = await client.call_tool("outtake_review", {"review_id": seeded["review_id"]})
            html = await _app_html(client)
            await page.evaluate("() => { document.body.style.margin = '0'; }")
            frame = await _mount(page, html, initial, theme="dark")
            await page.evaluate("() => { document.querySelector('#app').style.height = '900px'; }")
            await expect(frame.locator("#source-title")).to_have_text(
                seeded["plan"].title, timeout=15000
            )
            await expect(frame.locator("#revision-label")).to_have_text("Revision 1")
            for selector in (
                "#mcp-review-controls",
                "#revision-select",
                "#adopt-head",
                "#mcp-refresh",
            ):
                assert await frame.locator(selector).count() == 0, selector

            await native.emulate_media(color_scheme="dark")
            await native.set_content(_native_html())
            critical = [
                "header",
                "#status",
                ".workspace",
                ".moments",
                ".viewer",
                ".editor",
                ".screen",
                "#trim-controls",
                "#filmstrip",
                "#edit-controls",
            ]
            for selector in critical:
                assert await frame.locator(selector).count() == 1
                assert await native.locator(selector).count() == 1
                portable_box = await frame.locator(selector).bounding_box()
                native_box = await native.locator(selector).bounding_box()
                assert portable_box and native_box, selector
                dimensions = (
                    ("width", "height") if selector in {"header", "#status"} else ("x", "width")
                )
                for key in dimensions:
                    assert portable_box[key] == pytest.approx(native_box[key], abs=1.0), (
                        selector,
                        key,
                        portable_box,
                        native_box,
                    )

            # The review uses the native custom playback surface, never browser
            # controls, and retains the native editing affordances.
            assert await frame.locator("#video").get_attribute("controls") is None
            assert await frame.locator("#video").evaluate("video => video.controls") is False
            for selector in (
                "#timeline-seek",
                "#start-slider",
                "#end-slider",
                "#play-selection",
                "#loop-selection",
                "#add-cue",
                "#format-buttons",
                "#moments-list",
                "#filmstrip",
            ):
                assert await frame.locator(selector).count() == 1, selector

            async def colors():
                return await frame.locator("body").evaluate(
                    """node => {
                        const style = getComputedStyle(node);
                        return {
                            background: style.backgroundColor,
                            foreground: style.color,
                            colorScheme: style.colorScheme,
                            theme: document.documentElement.dataset.theme,
                        };
                    }"""
                )

            dark = await colors()
            assert dark["theme"] == "dark"
            await page.evaluate("() => window.setOuttakeHostContext({theme:'light'})")
            await expect(frame.locator("html")).to_have_attribute("data-theme", "light")
            light = await colors()
            assert light["background"] != dark["background"]
            assert light["foreground"] != dark["foreground"]

            # Reattach without an explicit theme to exercise the native system
            # media query. The host SDK only permits explicit light/dark values.
            await page.emulate_media(color_scheme="light")
            frame = await _mount(page, html, initial, theme=None)
            await expect(frame.locator("html")).to_have_attribute("data-theme", "system")
            system_light = await colors()
            assert system_light["background"] == light["background"]
            assert system_light["colorScheme"] == "light"

            await page.emulate_media(color_scheme="dark")
            system_dark = await colors()
            assert system_dark["background"] == dark["background"]
            assert system_dark["foreground"] == dark["foreground"]
            assert system_dark["colorScheme"] == "dark"
            assert not any(call["name"] == "outtake_admit" for call in calls)
            await browser.close()

    asyncio.run(run())


def test_mcp_app_preserves_custom_trim_playback_and_full_cue_fields(tool, fixture_video):
    """Native trim/playback controls edit and retain complete semantic cues."""

    script = _host_bundle()

    async def run():
        seeded = seed_plan_review(tool, fixture_video)
        async with (
            Client(create_server(tool.settings, [seeded["review_id"]])) as client,
            async_playwright() as playwright,
        ):
            browser = await playwright.chromium.launch()
            page = await browser.new_page(viewport={"width": 1180, "height": 900})
            calls = []

            async def host_call(arguments):
                calls.append(arguments)
                return _wire(
                    await client.call_tool(arguments["name"], arguments.get("arguments", {}))
                )

            async def host_read(arguments):
                return _wire(await client.read_resource(arguments["uri"]))

            await page.expose_function("hostCall", host_call)
            await page.expose_function("hostRead", host_read)
            await page.goto("about:blank")
            await page.add_script_tag(content=script)
            initial = await client.call_tool("outtake_review", {"review_id": seeded["review_id"]})
            frame = await _mount(page, await _app_html(client), initial)
            await expect(frame.locator("#video")).to_be_visible(timeout=15000)

            await frame.locator("#loop-selection").click()
            await expect(frame.locator("#loop-selection")).to_have_attribute("aria-pressed", "true")
            assert await frame.locator("#video").evaluate("video => video.controls") is False

            # The handles are the native range controls; the hidden plan fields
            # are not used as browser-facing inputs.
            await frame.locator("#start-slider").fill("0.2")
            await frame.locator("#end-slider").fill("0.9")
            await frame.locator("#frame").fill("0.8")
            assert float(
                await frame.locator("#start").evaluate("node => node.value")
            ) == pytest.approx(0.6)
            assert float(
                await frame.locator("#end").evaluate("node => node.value")
            ) == pytest.approx(1.3)
            await frame.locator("#play-selection").click()
            await frame.locator("#play-selection").click()

            await frame.locator("#add-cue").click()
            await frame.locator("#overlay-text").fill("A styled retained cue")
            await frame.locator("#cue-start").fill("0.10")
            await frame.locator("#cue-end").fill("0.55")
            await frame.locator("#text-appearance summary").click()
            await frame.locator("#text-size").fill("48")
            await frame.locator("#text-color").fill("#ff00aa")
            await frame.locator("#outline-width").fill("4")
            await frame.locator("#text-x").fill("0.25")
            await frame.locator("#text-y").fill("0.7")
            await expect(frame.locator("#dirty-label")).to_contain_text(
                "Draft saved", timeout=15000
            )

            retained = tool.review_snapshot(seeded["review_id"])
            cue = retained["draft"]["value"]["cues"][0]
            assert cue["text"] == "A styled retained cue"
            assert cue["origin"] == "manual"
            assert cue["start"] == pytest.approx(0.7)
            assert cue["end"] == pytest.approx(1.15)
            assert cue["size"] == 48
            assert cue["color"] == "#ff00aa"
            assert cue["outline_width"] == 4
            assert cue["x"] == pytest.approx(0.25)
            assert cue["y"] == pytest.approx(0.70)
            assert "font" in cue and "alignment" in cue
            assert "caption_text" not in retained["draft"]["value"]

            applied = _data(
                await client.call_tool(
                    "outtake_apply_changes",
                    {
                        "review_id": seeded["review_id"],
                        "plan_id": seeded["plan"].id,
                        "changes": retained["draft"]["value"],
                        "request_id": "browser-agent-cue-apply",
                    },
                )
            )
            revised = applied["plan"]
            applied_cue = revised["cues"][0]
            assert applied_cue["text"] == cue["text"]
            assert applied_cue["color"] == cue["color"]
            assert applied_cue["outline_width"] == cue["outline_width"]
            assert not any(
                call["name"] in {"outtake_caption_tracks", "outtake_import_captions"}
                for call in calls
            )
            await browser.close()

    asyncio.run(run())
