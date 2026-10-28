"""Run-bound stdio MCP application server. No evaluator or credentials are loaded."""
import argparse
from pathlib import Path
import sys
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError
from goalflow_world.models import Task
from goalflow_world.store import LabWorld, ROOT, SAFE, WorldError
from goalflow_world.workflow import RevisionBrief


def create_server(world):
    server = FastMCP('cedar-studio-local-world', log_level='CRITICAL')

    def invoke(operation, *args):
        try:
            return {'ok': True, 'result': operation(*args)}
        except WorldError as exc:
            return {'ok': False, 'error': str(exc)}
        except ValidationError:
            return {'ok': False, 'error': 'Invalid application record; check the tool schema'}
        except Exception:
            # Never emit raw DB paths, exception bodies, or tracebacks to the agent.
            return {'ok': False, 'error': 'Local operation failed; operator inspection required'}

    @server.tool()
    def get_world() -> dict:
        """Read visible documents/messages/tasks/decisions and the brief output contract for this run."""
        return invoke(world.workflow_context)

    @server.tool()
    def get_activity() -> dict:
        """Read already-recorded application activity, never scheduled future events."""
        return invoke(world.timeline)

    @server.tool()
    def send_message(recipient: str, topic: Literal['review_request', 'clarification', 'reminder', 'status_request'],
                     body: str, request_id: str, artifact_version: int | None = None,
                     subject: Literal['form_layout', 'scope', 'review_status'] | None = None) -> dict:
        """Send a LOCAL request. Clarifications require a subject code; other messages can use null. Retry the same request ID/arguments."""
        return invoke(world.send_message, recipient, topic, body, request_id, artifact_version, subject)

    @server.tool()
    def advance_clock(minutes: int, request_id: str | None = None) -> dict:
        """Wait 0–960 business minutes within the horizon. Reuse request_id to retry without advancing twice."""
        return invoke(world.advance, minutes, request_id)

    @server.tool()
    def record_decision(message_id: str) -> dict:
        """Record an actually delivered decision from the current authorized decision maker."""
        return invoke(world.record_decision, message_id)

    @server.tool()
    def update_task(task: Task, request_id: str) -> dict:
        """Create/update an allowed task. Preserve unrelated tasks; supply evidence and acceptance conditions."""
        return invoke(world.upsert_task, task.model_dump(), request_id)

    @server.tool()
    def publish_brief(brief_id: str, brief: RevisionBrief, request_id: str) -> dict:
        """Save an immutable LOCAL brief revision. This does not certify its truth or approval."""
        return invoke(world.publish_brief, brief_id, brief.model_dump(), request_id)

    @server.tool()
    def read_brief(brief_id: str, revision: int) -> dict:
        """Read back the exact saved brief and Markdown, recording its hash and read receipt."""
        return invoke(world.read_brief, brief_id, revision)

    @server.tool()
    def report_outcome(status: Literal['completed', 'blocked', 'incomplete'], brief_id: str, revision: int, request_id: str) -> dict:
        """Record completed/blocked/incomplete as an agent CLAIM, not an evaluator result."""
        return invoke(world.report_outcome, status, brief_id, revision, request_id)

    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--runs-root', type=Path, default=ROOT/'runs')
    args = parser.parse_args()
    if not SAFE.fullmatch(args.run):
        parser.error('Invalid run ID')
    run_root = args.runs_root.resolve()
    run_path = (run_root/args.run).resolve()
    if run_path.parent != run_root:
        parser.error('Run must be directly inside the configured runs root')
    create_server(LabWorld(run_path)).run(transport='stdio')
