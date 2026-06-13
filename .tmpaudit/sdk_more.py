"""Test executions.get, executions.tree, watch, presets, approvals.list."""
import asyncio, json, traceback
from abenix_sdk import Abenix, ActingSubject

API_KEY = "af_luhS8NNNz0e1VoteEuspMFbM1X2GNeEPNt0HQMBjtgQ"
BASE = "http://localhost:8000"
AGENT_ID = "9cb47129-47c3-4d7b-8681-92dee67f715c"
EXEC_ID  = "4642eef7-4fba-408d-aead-e307a991965d"

async def main():
    results = {}
    async with Abenix(api_key=API_KEY, base_url=BASE, timeout=60.0) as forge:
        # executions.get
        try:
            row = await forge.executions.get(EXEC_ID)
            results["exec_get_keys"] = sorted(list((row or {}).keys()))[:15]
            results["exec_get_status"] = (row or {}).get("status")
        except Exception as e:
            results["exec_get_error"] = repr(e)

        # executions.tree
        try:
            tree = await forge.executions.tree(EXEC_ID)
            results["tree_top_keys"] = sorted(list((tree or {}).keys()))[:15]
        except Exception as e:
            results["tree_error"] = repr(e)

        # approvals.list
        try:
            ap = await forge.approvals.list(limit=3)
            results["approvals_list_count"] = len(ap)
        except Exception as e:
            results["approvals_list_error"] = repr(e)

        # presets.list
        try:
            ps = await forge.presets.list()
            results["presets_count"] = len(ps)
        except Exception as e:
            results["presets_error"] = repr(e)

        # knowledge.search (gracefully should 404 / fail if no KB)
        # skip — needs a kb_id we may not have.

        # try forge.watch on a freshly-started execution
        try:
            er = await forge.execute(AGENT_ID, "Reply OK.", wait="submitted")
            new_eid = er.execution_id
            results["watch_exec_id"] = new_eid
            snapshots = []
            import asyncio as _a
            async def collect():
                async for snap in forge.watch(new_eid):
                    snapshots.append({"status": snap.status, "current_node_id": snap.current_node_id, "is_terminal": snap.is_terminal})
                    if snap.is_terminal or len(snapshots) > 30:
                        break
            try:
                await _a.wait_for(collect(), timeout=45)
            except _a.TimeoutError:
                pass
            results["watch_snapshot_count"] = len(snapshots)
            results["watch_first_three"] = snapshots[:3]
            results["watch_terminal"] = snapshots and snapshots[-1]["is_terminal"]
        except Exception as e:
            results["watch_error"] = repr(e)
            results["watch_tb"] = traceback.format_exc()[-600:]

    print(json.dumps(results, indent=2, default=str))

asyncio.run(main())
