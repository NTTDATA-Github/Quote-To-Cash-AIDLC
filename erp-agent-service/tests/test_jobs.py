import importlib


def _fresh_jobs_module(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    import service.jobs as jobs_module

    return importlib.reload(jobs_module)


def test_enqueue_claim_finish_round_trip(tmp_path, monkeypatch):
    jobs = _fresh_jobs_module(tmp_path, monkeypatch)

    run_id = jobs.enqueue(
        "SAP",
        [
            {
                "erp_field": "KUNNR",
                "canonical_field": "customer_id",
                "sample_data": "C1",
                "confidence": 97,
            }
        ],
    )
    assert jobs.get(run_id)["status"] == "PENDING"

    claimed = jobs.claim_pending()
    assert [r["id"] for r in claimed] == [run_id]
    assert jobs.get(run_id)["status"] == "PROCESSING"
    assert jobs.claim_pending() == []

    jobs.finish(run_id, result={"branch": "agent/x", "pr_url": "https://example.com/pr/1"})
    done = jobs.get(run_id)
    assert done["status"] == "DONE"
    assert done["result_json"]


def test_finish_with_error_marks_failed(tmp_path, monkeypatch):
    jobs = _fresh_jobs_module(tmp_path, monkeypatch)
    run_id = jobs.enqueue("SAP", [])
    jobs.claim_pending()
    jobs.finish(run_id, error="boom")
    assert jobs.get(run_id)["status"] == "FAILED"
    assert jobs.get(run_id)["error"] == "boom"
