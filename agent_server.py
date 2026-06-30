import asyncio
import os
import json
import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import uvicorn

from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.hooks import policy
from google.antigravity.hooks import hooks
from google.antigravity import types

# Initialize FastAPI
app = FastAPI(title="Antigravity Voice Agent")

# Define the models
class ChatRequest(BaseModel):
    text: str

TTS_URL = "http://127.0.0.1:8765/speak"
EVENT_URL = "http://127.0.0.1:8765/event"

async def speak(text: str, event_type: str = "MESSAGE"):
    """Helper to send text to the gencan-sse TTS server."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(TTS_URL, json={
                "text": text,
                "event_type": event_type,
                "priority": 2
            })
    except Exception as e:
        print(f"Failed to speak: {e}")

# Hooks to announce tool usage
@hooks.pre_tool_call_decide
async def announce_tool(data: types.ToolCall) -> types.HookResult:
    print(f"Running tool: {data.name}")
    # Tell the user we are using a tool (this will be spoken)
    # Using event_type TOOL_USE so it uses the 'Puck' voice if configured
    await speak(f"{data.name}", event_type="TOOL_USE")
    return types.HookResult(allow=True)

# Build the agent config
agent_config = LocalAgentConfig(
    system_instructions=(
        "You are an autonomous AI agent running on the user's local machine. "
        "You have full access to their filesystem and terminal. "
        "Use your tools to help them. Keep your spoken responses conversational and concise."
    ),
    policies=[policy.allow_all()], # Unfettered access
    hooks=[announce_tool],
    mcp_servers=[
        types.McpStdioServer(
            name="github",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")}
        )
    ]
)

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    print(f"Received chat: {request.text}")
    # Announce thinking
    await speak("Thinking...", event_type="THINKING")
    
    try:
        async with Agent(agent_config) as agent:
            # Send the user's text to the agent
            response = await agent.chat(request.text)
            
            # The agent executes tools automatically during chat().
            # Once it's done, we get the final text.
            final_text = await response.text()
            print(f"Agent response: {final_text}")
            
            # Speak the final response
            await speak(final_text, event_type="MESSAGE")
            
            return {"status": "ok", "response": final_text}
    except Exception as e:
        print(f"Agent error: {e}")
        await speak(f"I encountered an error: {e}", event_type="ERROR")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8767)
