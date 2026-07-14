import unittest

from soccer_ratings.jobs import JobManager


class JobManagerTests(unittest.TestCase):
    def test_create_returns_running_job_with_zeroed_progress(self) -> None:
        jobs = JobManager()
        job_id = jobs.create(kind="country_import", label="/England/")
        job = jobs.get(job_id)
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["current"], 0)
        self.assertEqual(job["total"], 0)
        self.assertTrue(jobs.is_running(job_id))

    def test_create_returns_unique_ids(self) -> None:
        jobs = JobManager()
        first = jobs.create(kind="country_import", label="/England/")
        second = jobs.create(kind="country_import", label="/England/")
        self.assertNotEqual(first, second)

    def test_get_unknown_job_returns_none(self) -> None:
        jobs = JobManager()
        self.assertIsNone(jobs.get("does-not-exist"))
        self.assertFalse(jobs.is_running("does-not-exist"))

    def test_run_records_progress_and_result(self) -> None:
        jobs = JobManager()
        job_id = jobs.create(kind="country_import", label="/England/")

        def task(on_progress):
            on_progress(1, 2, "Premier League")
            on_progress(2, 2, "Championship")
            return {"leagues_processed": 2}

        jobs.run(job_id, task)

        job = jobs.get(job_id)
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["current"], 2)
        self.assertEqual(job["total"], 2)
        self.assertEqual(job["message"], "Done")
        self.assertEqual(job["result"], {"leagues_processed": 2})
        self.assertFalse(jobs.is_running(job_id))

    def test_run_records_error_without_raising(self) -> None:
        jobs = JobManager()
        job_id = jobs.create(kind="country_import", label="/England/")

        def task(on_progress):
            raise RuntimeError("scrape failed")

        jobs.run(job_id, task)

        job = jobs.get(job_id)
        self.assertEqual(job["status"], "error")
        self.assertIn("scrape failed", job["error"])
        self.assertFalse(jobs.is_running(job_id))


if __name__ == "__main__":
    unittest.main()
