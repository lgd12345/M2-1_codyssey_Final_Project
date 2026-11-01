from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from uuid import uuid4

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
sys.path.insert(0, str(ROOT))

from app.agent_rag.runner import run_manual_agent


async def _run(question: str, asset_dir: Path) -> dict:
    result = await run_manual_agent(question)
    asset_dir.mkdir(parents=True, exist_ok=True)
    output = result.to_dict()
    for asset in result.assets:
        filename = f"{asset.asset_id}.png"
        (asset_dir / filename).write_bytes(asset.data)
        for item in output["assets"]:
            if item["asset_id"] == asset.asset_id:
                item["local_file"] = str(asset_dir / filename)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask the manual RAG backend agent (no frontend required).")
    parser.add_argument("question", help="question for the manual agent")
    parser.add_argument("--asset-dir", type=Path, default=None,
                        help="where to save pages opened by the agent; defaults under backend/data/agent_runs")
    args = parser.parse_args()
    output_dir = args.asset_dir or ROOT / "data/agent_runs" / str(uuid4())
    result = asyncio.run(_run(args.question, output_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
