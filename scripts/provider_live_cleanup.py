#!/usr/bin/env python3
"""Reconcile only explicitly recorded fixture names in the isolated validation DB."""

import json
import os
from pathlib import Path

from provider_live_validation import Api


def main():
    assert os.environ.get("LIVE_VALIDATION_CONFIRM") == "isolated-qa-only", "Explicit isolated-QA opt-in is required"
    database = os.environ["AGENT_MEMORY_TEST_DATABASE_ID"]
    folder = Path(os.environ["LIVE_RESULTS_DIRECTORY"])
    names = set()
    for path in folder.glob("intent-*.json"):
        intent = json.loads(path.read_text())
        assert intent["database_id"] == database, "Intent belongs to another database"
        assert intent["fixture"].startswith(("tfacc-live-", "tfacc-upgrade-")), "Unexpected fixture intent"
        names.update(intent["names"])
    api = Api()
    reconciled = []
    for store in api.stores(database):
        if store.get("name") in names:
            api.wait(api.request("/memory-stores/" + store["storeId"], "DELETE"))
            reconciled.append(store["storeId"])
    assert not [s for s in api.stores(database) if s.get("name") in names], "Recorded fixture cleanup unverified"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "emergency-cleanup.json").write_text(json.dumps({"cleanup_verified": True, "reconciled_store_ids": reconciled}))
    print("All recorded temporary fixture stores are absent; baseline QA stores preserved.")


if __name__ == "__main__":
    main()
