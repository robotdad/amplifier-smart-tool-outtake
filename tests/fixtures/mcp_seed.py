"""Provider-free retained Outtake work for the independent MCP Apps host."""

# fmt: off

import hashlib

from outtake.discovery import save_record


def seed_plan_review(tool, source, *, start=0.4, end=1.6, title="Green handoff"):
    """Create real retained plan/output state and explicitly authorize it."""
    plan = tool.plan(
        str(source),
        start,
        end,
        title=title,
        format="mp4",
        profile="share",
        captions_enabled=False,
    )
    receipt = tool.render(plan)
    review = tool.open_review("artifact", receipt["artifact_id"], scope="mcp-browser")
    return {
        "plan": plan,
        "receipt": receipt,
        "review": review,
        "review_id": review["review_id"],
    }


def seed_finding_review(tool, source):
    """Retain source-linked evidence and a needs-selection finding without a model."""
    plan = tool.plan(
        str(source),
        0.3,
        2.0,
        title="Blue transition",
        captions_enabled=False,
    )
    evidence = tool.review_frames(plan)
    source_id = evidence["source_id"]
    finding_id = "finding_" + hashlib.sha256(
        f"mcp-browser:{source}".encode()
    ).hexdigest()
    candidate_id = "candidate_" + hashlib.sha256(
        f"{finding_id}:candidate".encode()
    ).hexdigest()
    finding = {
        "id": finding_id,
        "status": "needs_selection",
        "request": {
            "title": "Known test moment",
            "description": "Review the green-to-blue transition in the generated source.",
            "context": "Provider-free fixture; this is a protocol check, not scene recognition.",
        },
        "candidates": [
            {
                "id": candidate_id,
                "title": "Green to blue transition",
                "source_id": source_id,
                "source_sha256": plan.source.sha256,
                "start": 0.8,
                "end": 1.8,
                "evidence_ids": [evidence["id"]],
                "explanation": "The retained frame evidence brackets the transition.",
                "uncertainty": "Sampled frames leave gaps; sound is unverified.",
                "human_confirmed": False,
            }
        ],
        "evidence_ids": [evidence["id"]],
        "absence_proven": False,
        "limitation": evidence["limitation"],
    }
    save_record(tool, "findings", finding)
    review = tool.open_review("finding", finding_id, scope="mcp-browser")
    return {
        "plan": plan,
        "evidence": evidence,
        "finding": finding,
        "review": review,
        "review_id": review["review_id"],
        "candidate_id": candidate_id,
    }
