import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import anthropic
from app.config import settings
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import TOOLS_SCHEMA, dispatch_tool
from app.paypal.client import PayPalAPIError

logger = logging.getLogger(__name__)

# In-memory session history storage: session_id -> list of message dicts
_sessions: Dict[str, List[Dict[str, Any]]] = {}


def get_session_history(session_id: str) -> List[Dict[str, Any]]:
    if session_id not in _sessions:
        _sessions[session_id] = []
    return _sessions[session_id]


def clear_session_history(session_id: str) -> None:
    if session_id in _sessions:
        _sessions[session_id] = []


def get_llm_client() -> Optional[anthropic.AsyncAnthropic]:
    if not settings.LLM_API_KEY:
        return None
    return anthropic.AsyncAnthropic(api_key=settings.LLM_API_KEY)


async def run_agent(
    session_id: str,
    user_message: str,
    client: Optional[anthropic.AsyncAnthropic] = None,
    max_steps: int = 5,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Execute tool-calling agent loop for a user message within a session.
    Returns (assistant_reply, actions_taken).
    """
    history = get_session_history(session_id)
    history.append({"role": "user", "content": user_message})

    actions_taken: List[Dict[str, Any]] = []
    llm_client = client or get_llm_client()

    if not llm_client:
        # Fallback if no LLM API key is provided
        fallback_msg = (
            "No LLM_API_KEY configured. Please configure your Anthropic API key in .env "
            "to enable the conversational AI agent."
        )
        history.append({"role": "assistant", "content": fallback_msg})
        return fallback_msg, []

    step = 0
    while step < max_steps:
        step += 1
        try:
            response = await llm_client.messages.create(
                model=settings.LLM_MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=TOOLS_SCHEMA,
                messages=history,
            )
        except Exception as exc:
            logger.error(f"Error calling LLM: {exc}")
            err_reply = f"I encountered an error communicating with the AI service: {str(exc)}"
            history.append({"role": "assistant", "content": err_reply})
            return err_reply, actions_taken

        # Check if model requested tool execution
        tool_calls = [block for block in response.content if getattr(block, "type", None) == "tool_use"]

        if not tool_calls:
            # Model finished, collect textual reply
            text_blocks = [block.text for block in response.content if getattr(block, "type", None) == "text"]
            reply_text = "\n".join(text_blocks).strip()
            history.append({"role": "assistant", "content": reply_text})
            return reply_text, actions_taken

        # Model issued tool call(s) - append assistant message with content blocks
        history.append({"role": "assistant", "content": response.content})

        # Process each tool call and collect results
        tool_results = []
        for call in tool_calls:
            tool_name = call.name
            tool_input = call.input
            tool_id = call.id

            logger.info(f"Executing tool {tool_name} with args {tool_input}")
            try:
                res = await dispatch_tool(tool_name, tool_input)
                actions_taken.append({"tool": tool_name, "input": tool_input, "output": res})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": json.dumps(res),
                })
            except PayPalAPIError as pperr:
                err_dict = {
                    "error": "PayPalAPIError",
                    "status_code": pperr.status_code,
                    "details": pperr.response_body,
                    "message": str(pperr),
                }
                actions_taken.append({"tool": tool_name, "input": tool_input, "error": err_dict})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "is_error": True,
                    "content": json.dumps(err_dict),
                })
            except Exception as err:
                err_dict = {"error": type(err).__name__, "message": str(err)}
                actions_taken.append({"tool": tool_name, "input": tool_input, "error": err_dict})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "is_error": True,
                    "content": json.dumps(err_dict),
                })

        # Feed tool execution results back to the model
        history.append({"role": "user", "content": tool_results})

    # If reached max steps
    fallback_reply = "I completed the available actions."
    history.append({"role": "assistant", "content": fallback_reply})
    return fallback_reply, actions_taken
