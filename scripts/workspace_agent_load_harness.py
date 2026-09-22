"""Read-only concurrency harness for Product Delivery and QA brief endpoints."""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time

import httpx


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--token", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--agent-workspace-id", required=True)
    parser.add_argument("--profile", choices=("delivery", "quality"), required=True)
    parser.add_argument("--release-id", default="")
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    if args.requests < 1 or args.concurrency < 1:
        raise ValueError("requests and concurrency must be positive")
    if args.profile == "quality" and not args.release_id:
        raise ValueError("--release-id is required for Quality")
    root = f"{args.base_url.rstrip('/')}/workspaces/{args.workspace_id}/agent-workspaces/{args.agent_workspace_id}"
    if args.profile == "delivery":
        endpoint = f"{root}/delivery/brief"
        payload = {
            "message": "Load-test the current delivery brief",
            "persist_history": False,
        }
    else:
        endpoint = f"{root}/quality/brief"
        payload = {
            "message": "Load-test the current quality readiness",
            "release_id": args.release_id,
        }
    semaphore = asyncio.Semaphore(args.concurrency)
    latencies: list[float] = []
    statuses: dict[int, int] = {}

    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {args.token}"}, timeout=args.timeout) as client:

        async def invoke() -> None:
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.post(endpoint, json=payload)
                    code = response.status_code
                except httpx.HTTPError:
                    code = 0
                latencies.append((time.perf_counter() - started) * 1_000)
                statuses[code] = statuses.get(code, 0) + 1

        await asyncio.gather(*(invoke() for _ in range(args.requests)))

    ordered = sorted(latencies)
    p95_index = min(len(ordered) - 1, max(0, round(len(ordered) * 0.95) - 1))
    successful = sum(count for code, count in statuses.items() if 200 <= code < 300)
    print(
        {
            "profile": args.profile,
            "requests": args.requests,
            "concurrency": args.concurrency,
            "success_rate": round(successful / args.requests * 100, 2),
            "latency_ms": {
                "mean": round(statistics.mean(ordered), 2),
                "p50": round(statistics.median(ordered), 2),
                "p95": round(ordered[p95_index], 2),
                "max": round(max(ordered), 2),
            },
            "statuses": statuses,
        }
    )
    return 0 if successful == args.requests else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(_arguments())))
