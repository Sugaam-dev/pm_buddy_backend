import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
import json

from app.ai.orchestrator import AIOrchestrator
from app.ai.tools import get_openai_tools, execute_tool, TOOL_METADATA


class InMemoryTestSession:
    """In-memory mock session supporting the AI orchestrator tests."""
    def __init__(self):
        self.added = []
        self.actions = {}

    def add(self, obj):
        self.added.append(obj)
        if hasattr(obj, "id"):
            self.actions[str(obj.id)] = obj

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def execute(self, stmt):
        class MockResult:
            def scalars(self):
                class MockScalars:
                    def all(self):
                        return []
                return MockScalars()
            def all(self):
                return []
            def scalar_one_or_none(self):
                return None
        return MockResult()


def make_mock_litellm_response(content=None, tool_calls=None):
    """Helper to mock LiteLLM / OpenAI response structure."""
    mock_choice = MagicMock()
    mock_message = MagicMock()
    mock_message.content = content
    mock_message.tool_calls = tool_calls
    mock_choice.message = mock_message
    
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


def make_mock_tool_call(call_id, name, arguments_dict):
    """Helper to construct tool_call object."""
    tc = MagicMock()
    tc.id = call_id
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments_dict)
    return tc


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_openai_tool_schemas_generation():
    """Verify tool catalog exports valid OpenAI/LiteLLM function calling schemas."""
    tools = get_openai_tools()
    assert len(tools) >= 6
    names = [t["function"]["name"] for t in tools]
    assert "get_my_work" in names
    assert "get_project_dashboard" in names
    assert "propose_calendar_meeting" in names
    for t in tools:
        assert t["type"] == "function"
        assert "parameters" in t["function"]
        assert "properties" in t["function"]["parameters"]


@pytest.mark.asyncio
async def test_litellm_tool_calling_loop_success():
    """
    Simulates:
    1. LLM requests tool call 'get_my_work'
    2. Orchestrator executes tool, appends result, and asks LLM again
    3. LLM returns conversational response with structured UI blocks retained
    """
    session = InMemoryTestSession()
    org_id = uuid4()
    user_id = uuid4()
    conv_id = uuid4()

    tool_call = make_mock_tool_call("call_123", "get_my_work", {"limit": 3})
    resp_step1 = make_mock_litellm_response(content=None, tool_calls=[tool_call])
    resp_step2 = make_mock_litellm_response(content="Here is your current workload for today.", tool_calls=None)

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.side_effect = [resp_step1, resp_step2]

        result = await AIOrchestrator.process_message(
            session=session,
            organization_id=org_id,
            user_id=user_id,
            conversation_id=conv_id,
            prompt="What tasks and tickets do I have?",
            user_permissions=["task.read"],
            force_llm=True,
        )

        assert mock_acompletion.call_count == 2
        assert "Here is your current workload for today." in result["text"]
        assert result["conversation_id"] == str(conv_id)


@pytest.mark.asyncio
async def test_sensitive_tool_call_hitl_interception():
    """
    Simulates:
    1. LLM attempts to call sensitive tool 'propose_calendar_meeting'
    2. Orchestrator intercepts call, creates WAITING_FOR_CONFIRMATION action proposal,
       attaches action_confirmation UI block, and terminates loop without direct mutation.
    """
    session = InMemoryTestSession()
    org_id = uuid4()
    user_id = uuid4()
    conv_id = uuid4()

    meeting_args = {
        "title": "Architecture Sign-off",
        "attendee_emails": ["alice@acme.com", "bob@acme.com"],
        "start_time": "2026-09-08T14:00:00Z",
        "end_time": "2026-09-08T14:30:00Z",
        "description": "Discuss microservices migration",
    }
    tool_call = make_mock_tool_call("call_meet_1", "propose_calendar_meeting", meeting_args)
    resp_step = make_mock_litellm_response(content=None, tool_calls=[tool_call])

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.return_value = resp_step

        result = await AIOrchestrator.process_message(
            session=session,
            organization_id=org_id,
            user_id=user_id,
            conversation_id=conv_id,
            prompt="Schedule architecture sign-off with Bob for 2 PM",
            user_permissions=["calendar.write"],
            force_llm=True,
        )

        # LiteLLM called once; loop paused because human confirmation is required
        assert mock_acompletion.call_count == 1
        assert "human confirmation is required" in result["text"].lower()

        # Check action_confirmation block
        action_blocks = [b for b in result["blocks"] if b["type"] == "action_confirmation"]
        assert len(action_blocks) == 1
        assert action_blocks[0]["action_id"] is not None
        assert action_blocks[0]["data"]["title"] == "Architecture Sign-off"


@pytest.mark.asyncio
async def test_tool_rbac_permission_denied():
    """
    Verifies that calling a tool without the required permission is rejected,
    returning an authorization error without executing the tool.
    """
    session = InMemoryTestSession()
    org_id = uuid4()
    user_id = uuid4()
    conv_id = uuid4()

    tool_call = make_mock_tool_call("call_proj_1", "get_project_dashboard", {"project_id": "ALPHA"})
    resp_step1 = make_mock_litellm_response(content=None, tool_calls=[tool_call])
    resp_step2 = make_mock_litellm_response(content="I could not access that project.", tool_calls=None)

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.side_effect = [resp_step1, resp_step2]

        # User only has calendar.read, lacks project.read
        result = await AIOrchestrator.process_message(
            session=session,
            organization_id=org_id,
            user_id=user_id,
            conversation_id=conv_id,
            prompt="Show me Project Alpha dashboard",
            user_permissions=["calendar.read"],
            force_llm=True,
        )

        assert mock_acompletion.call_count == 2
        # Check that the tool output sent to LLM contains the permission error
        second_call_messages = mock_acompletion.call_args_list[1][1]["messages"]
        tool_response_msg = next((m for m in second_call_messages if m.get("role") == "tool"), None)
        assert tool_response_msg is not None
        assert "Permission denied" in tool_response_msg["content"]


@pytest.mark.asyncio
async def test_tool_pydantic_validation_error():
    """
    Verifies that malformed arguments (missing required field) fail Pydantic validation
    gracefully and do not raise unhandled 500 exceptions.
    """
    session = InMemoryTestSession()
    org_id = uuid4()
    user_id = uuid4()
    conv_id = uuid4()

    # Missing required 'project_id'
    tool_call = make_mock_tool_call("call_invalid", "get_project_dashboard", {})
    resp_step1 = make_mock_litellm_response(content=None, tool_calls=[tool_call])
    resp_step2 = make_mock_litellm_response(content="Missing project ID.", tool_calls=None)

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.side_effect = [resp_step1, resp_step2]

        result = await AIOrchestrator.process_message(
            session=session,
            organization_id=org_id,
            user_id=user_id,
            conversation_id=conv_id,
            prompt="Show me dashboard",
            user_permissions=["project.read"],
            force_llm=True,
        )

        assert mock_acompletion.call_count == 2
        second_call_messages = mock_acompletion.call_args_list[1][1]["messages"]
        tool_response_msg = next((m for m in second_call_messages if m.get("role") == "tool"), None)
        assert tool_response_msg is not None
        assert "Invalid arguments" in tool_response_msg["content"]


@pytest.mark.asyncio
async def test_unknown_tool_rejection():
    """Verifies that an unknown tool name returned by LLM is safely handled."""
    session = InMemoryTestSession()
    org_id = uuid4()
    user_id = uuid4()
    conv_id = uuid4()

    tool_call = make_mock_tool_call("call_bad", "run_arbitrary_code", {"cmd": "rm -rf"})
    resp_step1 = make_mock_litellm_response(content=None, tool_calls=[tool_call])
    resp_step2 = make_mock_litellm_response(content="I cannot execute arbitrary code.", tool_calls=None)

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.side_effect = [resp_step1, resp_step2]

        result = await AIOrchestrator.process_message(
            session=session,
            organization_id=org_id,
            user_id=user_id,
            conversation_id=conv_id,
            prompt="Run this code for me",
            user_permissions=["admin"],
            force_llm=True,
        )

        assert mock_acompletion.call_count == 2
        second_call_messages = mock_acompletion.call_args_list[1][1]["messages"]
        tool_response_msg = next((m for m in second_call_messages if m.get("role") == "tool"), None)
        assert tool_response_msg is not None
        assert "not recognized" in tool_response_msg["content"]


@pytest.mark.asyncio
async def test_max_tool_iterations_guard():
    """Verifies that the orchestrator terminates after MAX_TOOL_ITERATIONS to prevent infinite loops."""
    session = InMemoryTestSession()
    org_id = uuid4()
    user_id = uuid4()
    conv_id = uuid4()

    # Model endlessly requests 'get_my_work'
    tool_call = make_mock_tool_call("loop_call", "get_my_work", {"limit": 1})
    resp_infinite = make_mock_litellm_response(content=None, tool_calls=[tool_call])

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.return_value = resp_infinite

        result = await AIOrchestrator.process_message(
            session=session,
            organization_id=org_id,
            user_id=user_id,
            conversation_id=conv_id,
            prompt="Loop forever",
            user_permissions=["task.read"],
            force_llm=True,
        )

        assert mock_acompletion.call_count == AIOrchestrator.MAX_TOOL_ITERATIONS
        assert result["conversation_id"] == str(conv_id)


@pytest.mark.asyncio
async def test_litellm_failure_falls_back_to_deterministic_router():
    """
    Verifies that if LiteLLM raises an API/network exception,
    the orchestrator catches it and transparently falls back to the deterministic intent router.
    """
    session = InMemoryTestSession()
    org_id = uuid4()
    user_id = uuid4()
    conv_id = uuid4()

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
        mock_acompletion.side_effect = Exception("LiteLLM API connection error: 503 Service Unavailable")

        result = await AIOrchestrator.process_message(
            session=session,
            organization_id=org_id,
            user_id=user_id,
            conversation_id=conv_id,
            prompt="What approvals are pending?",
            user_permissions=["approval.read"],
            force_llm=True,
        )

        # Fallback router handled the prompt cleanly
        assert "approval" in result["text"].lower()
        assert any(b["type"] == "approval_list" for b in result["blocks"])
