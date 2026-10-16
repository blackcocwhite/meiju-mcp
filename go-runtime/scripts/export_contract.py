"""Refresh only tool schemas from the Python reference, without starting a server."""

import asyncio
import json
from pathlib import Path

from meiju_mcp.server import create_server


async def main():
    tools = await create_server().list_tools()
    destination = Path(__file__).resolve().parents[1] / "contract/tools.json"
    destination.write_text(
        json.dumps(
            [t.model_dump(by_alias=True, exclude_none=True) for t in tools], ensure_ascii=False, indent=2
        )
        + "\n"
    )


if __name__ == "__main__":
    asyncio.run(main())
