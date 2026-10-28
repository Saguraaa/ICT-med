"""AgentArts deployment entrypoint. Requires the actual agentarts-sdk package."""
import asyncio
import os

from agentarts.sdk import AgentArtsRuntimeApp, RequestContext
from starlette.responses import JSONResponse

from config import load_env
from service import handle_payload

load_env()
app = AgentArtsRuntimeApp()


@app.entrypoint
async def handler(payload: dict, context: RequestContext = None) -> JSONResponse:
    session_id = getattr(context, 'session_id', None) if context else None
    result = await asyncio.to_thread(handle_payload, payload, session_id)
    # Older Windows PowerShell can misdecode JSON without an explicit response charset.
    return JSONResponse(result, media_type='application/json; charset=utf-8')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('AGENT_RUN_PORT', '8080')))
