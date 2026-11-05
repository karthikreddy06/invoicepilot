import asyncio
import inspect
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from openai import AsyncOpenAI, RateLimitError, OpenAIError

from app.config import settings
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import TOOLS_SCHEMA, dispatch_tool
from app.paypal.client import PayPalAPIError

logger = logging.getLogger(__name__)

# In-memory session history storage: session_id -> list of message dicts
_sessions: Dict[str, List[Dict[str, Any]]] = {}


def get_session_history(session_id: str) -> List[Dict[str, Any]]:
    if session_id not in _sessions:
        # Initialize session with system prompt
        _sessions[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    return _sessions[session_id]


def clear_session_history(session_id: str) -> None:
    if session_id in _sessions:
        _sessions[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]


def get_llm_client() -> Optional[AsyncOpenAI]:
    if not settings.LLM_API_KEY:
        return None
    return AsyncOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
    )


async def _call_chat_completion(
    client: Any,
    messages: List[Dict[str, Any]],
    max_retries: int = 2,
) -> Any:
    """Call chat.completions.create with short retry backoff for rate-limit errors (429)."""
    attempt = 0
    while True:
        try:
            res = client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=messages,
                tools=TOOLS_SCHEMA,
            )
            if inspect.isawaitable(res):
                return await res
            return res
        except RateLimitError as rle:
            attempt += 1
            if attempt > max_retries:
                logger.error(f"Rate limit exceeded after {max_retries} retries: {rle}")
                raise
            sleep_sec = 1.5 * attempt
            logger.warning(f"Rate limited (429). Retrying in {sleep_sec}s (attempt {attempt}/{max_retries})...")
            await asyncio.sleep(sleep_sec)
        except Exception as exc:
            # Check for generic status_code == 429
            if getattr(exc, "status_code", None) == 429 and attempt < max_retries:
                attempt += 1
                sleep_sec = 1.5 * attempt
                logger.warning(f"Status 429 detected. Retrying in {sleep_sec}s (attempt {attempt}/{max_retries})...")
                await asyncio.sleep(sleep_sec)
                continue
            raise


async def run_agent(
    session_id: str,
    user_message: str,
    client: Optional[Any] = None,
    max_steps: int = 5,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Execute tool-calling agent loop for a user message within a session using OpenAI-compatible client.
    Returns (assistant_reply, actions_taken).
    """
    history = get_session_history(session_id)
    history.append({"role": "user", "content": user_message})

    actions_taken: List[Dict[str, Any]] = []
    llm_client = client or get_llm_client()

    if not llm_client:
        fallback_msg = (
            "No LLM_API_KEY configured. Please configure your LLM provider API key in .env "
            "to enable the conversational AI agent."
        )
        history.append({"role": "assistant", "content": fallback_msg})
        return fallback_msg, []

    step = 0
    while step < max_steps:
        step += 1
        try:
            response = await _call_chat_completion(llm_client, history)
        except RateLimitError:
            rate_limit_msg = (
                "The AI service is currently experiencing high demand (rate limit reached). "
                "Please wait a few moments and try your request again."
            )
            history.append({"role": "assistant", "content": rate_limit_msg})
            return rate_limit_msg, actions_taken
        except Exception as exc:
            if getattr(exc, "status_code", None) == 429:
                rate_limit_msg = (
                    "The AI service is currently experiencing high demand (rate limit reached). "
                    "Please wait a few moments and try your request again."
                )
                history.append({"role": "assistant", "content": rate_limit_msg})
                return rate_limit_msg, actions_taken

            logger.error(f"Error calling LLM: {exc}")
            err_reply = f"I encountered an error communicating with the AI service: {str(exc)}"
            history.append({"role": "assistant", "content": err_reply})
            return err_reply, actions_taken

        choice = response.choices[0]
        message = choice.message
        tool_calls = getattr(message, "tool_calls", None)

        if not tool_calls:
            # Model responded with plain text
            reply_text = message.content or ""
            history.append({"role": "assistant", "content": reply_text})
            return reply_text, actions_taken

        # Build assistant turn message including tool calls for history
        serializable_tool_calls = []
        for tc in tool_calls:
            fn_name = tc.function.name if hasattr(tc.function, "name") else tc.function.get("name")
            fn_args = tc.function.arguments if hasattr(tc.function, "arguments") else tc.function.get("arguments")
            serializable_tool_calls.append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": fn_name,
                    "arguments": fn_args,
                },
            })

        history.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": serializable_tool_calls,
        })

        # Process each tool call and append a tool response message
        for tc in tool_calls:
            tc_id = tc.id
            fn_name = tc.function.name if hasattr(tc.function, "name") else tc.function.get("name")
            fn_args_raw = tc.function.arguments if hasattr(tc.function, "arguments") else tc.function.get("arguments")

            try:
                fn_args = json.loads(fn_args_raw) if isinstance(fn_args_raw, str) else fn_args_raw
            except Exception as e:
                logger.error(f"Failed to parse tool arguments: {fn_args_raw}")
                fn_args = {}

            logger.info(f"Executing tool {fn_name} with args {fn_args}")
            try:
                res = await dispatch_tool(fn_name, fn_args)
                actions_taken.append({"tool": fn_name, "input": fn_args, "output": res})
                history.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": fn_name,
                    "content": json.dumps(res),
                })
            except PayPalAPIError as pperr:
                err_dict = {
                    "error": "PayPalAPIError",
                    "status_code": pperr.status_code,
                    "details": pperr.response_body,
                    "message": str(pperr),
                }
                actions_taken.append({"tool": fn_name, "input": fn_args, "error": err_dict})
                history.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": fn_name,
                    "content": json.dumps(err_dict),
                })
            except Exception as err:
                err_dict = {"error": type(err).__name__, "message": str(err)}
                actions_taken.append({"tool": fn_name, "input": fn_args, "error": err_dict})
                history.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": fn_name,
                    "content": json.dumps(err_dict),
                })

    fallback_reply = "I completed the available actions."
    history.append({"role": "assistant", "content": fallback_reply})
    return fallback_reply, actions_taken
