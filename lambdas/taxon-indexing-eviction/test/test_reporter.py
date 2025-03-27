# type: ignore

from chalicelib import reporter
import test.test_data as test_data
import pytest


@pytest.fixture(autouse=True)
def reset_reporter():
    reporter._warnings = []
    reporter._errors = []
    reporter._final_report = {
        "warnings": reporter._warnings,
        "errors": reporter._errors,
    }


class TestReportTaskStatuses:
    def test_reports_task_statuses(self, mocker):
        spy_logger = mocker.spy(reporter, "logger")

        reporter.report_task_statuses(test_data.task_statuses)

        spy_logger.info.assert_called_once_with(
            "Task report: %s running tasks, %s missing tasks, %s failed tasks, %s succeeded tasks: %s",
            1,
            1,
            1,
            1,
            test_data.task_statuses,
        )

        assert reporter._final_report["task_statuses"] == test_data.task_statuses


class TestReportTaskCleanup:
    def test_reports_task_cleanup(self, mocker):
        spy_logger = mocker.spy(reporter, "logger")

        succeeded_deletion_report = {
            "tasks": ["aaaa-1111-aaaa-1111:1111"],
            "response": {"success": True},
        }
        failed_deletion_report = {
            "tasks": ["bbbb-2222-bbbb-2222:2222"],
            "response": {"success": True},
        }
        pipeline_run_deletion_report = {
            "pipeline_runs": ["pipeline_run_1"],
            "response": {"success": True},
        }

        task_cleanup_report = {
            "succeeded": succeeded_deletion_report,
            "failed": failed_deletion_report,
            "pipeline_runs_deleted": pipeline_run_deletion_report,
        }

        reporter.report_task_cleanup(
            succeeded_deletion_report,
            pipeline_run_deletion_report,
            failed_deletion_report,
        )

        spy_logger.info.assert_called_once_with(
            "Task cleanup report: %s", task_cleanup_report
        )

        assert reporter._final_report["task_cleanup_report"] == task_cleanup_report
        assert reporter._final_report["warnings"] == []

    def test_reports_warnings(self, mocker):
        spy_logger = mocker.spy(reporter, "logger")

        succeeded_deletion_report = {
            "tasks": ["aaaa-1111-aaaa-1111:1111"],
            "response": {"error": "error"},
        }
        failed_deletion_report = {
            "tasks": ["bbbb-2222-bbbb-2222:2222"],
            "response": {"success": True},
        }
        pipeline_run_deletion_report = {
            "pipeline_runs": ["pipeline_run_1"],
            "response": {"success": True},
        }

        task_cleanup_report = {
            "succeeded": succeeded_deletion_report,
            "failed": failed_deletion_report,
            "pipeline_runs_deleted": pipeline_run_deletion_report,
        }

        reporter.report_task_cleanup(
            succeeded_deletion_report,
            pipeline_run_deletion_report,
            failed_deletion_report,
        )

        spy_logger.info.assert_called_once_with(
            "Task cleanup report: %s", task_cleanup_report
        )

        assert reporter._final_report["task_cleanup_report"] == task_cleanup_report
        assert reporter._final_report["warnings"] == [
            {
                "message": "Succeeded task deletion failed",
                "details": succeeded_deletion_report,
            }
        ]


class TestReportCapacity:
    def test_reports_capacity_zero(self, mocker):
        spy_logger = mocker.spy(reporter, "logger")

        reporter.report_capacity(0)
        spy_logger.info.assert_called_once_with(
            "Max deletion task concurrency %s reached. No tasks started.", 0
        )

        assert reporter._final_report["capacity"] == 0

    def test_reports_capacity_nonzero(self, mocker):
        spy_logger = mocker.spy(reporter, "logger")

        reporter.report_capacity(2)
        spy_logger.info.assert_called_once_with(
            "Max deletion task concurrency %s not reached. Starting tasks... ", 2
        )

        assert reporter._final_report["capacity"] == 2


class TestReportEvictionCandidates:
    def test_reports_candidates(self, mocker):
        spy_logger = mocker.spy(reporter, "logger")

        by_pipeline_candidates = ["pipeline_run_1", "pipeline_run_2"]
        by_pipeline_and_background_id_candidates = {
            "background_id_1": ["pipeline_run_3"],
        }

        reporter.report_eviction_candidates(
            by_pipeline_candidates, by_pipeline_and_background_id_candidates
        )

        spy_logger.info.assert_called_once_with(
            "Deletion candidates: %s by pipeline, %s by pipeline and background id: %s",
            2,
            1,
            {
                "by_pipeline": by_pipeline_candidates,
                "by_pipeline_and_background_id": by_pipeline_and_background_id_candidates,
            },
        )


class TestReportEvictionsStarted:
    def test_reports_evictions_started(self, mocker):
        spy_logger = mocker.spy(reporter, "logger")

        by_pipeline_evictions_started = [
            {
                "pipeline_run_ids": ["pipeline_run_id_1", "pipeline_run_id_2"],
                "start_eviction_response": {"task": "aaaa-1111-aaaa-1111:1111"},
                "set_task_id_response": {"success": True},
            }
        ]

        by_pipeline_run_and_background_id_evictions_started = [
            {
                "background_id": "1",
                "pipeline_run_ids": ["pipeline_run_id_1", "pipeline_run_id_2"],
                "start_eviction_response": {"task": "aaaa-1111-aaaa-1111:1111"},
                "set_task_id_response": {"success": True},
            }
        ]

        reporter.report_evictions_started(
            by_pipeline_evictions_started, "by_pipeline_run_id"
        )
        reporter.report_evictions_started(
            by_pipeline_run_and_background_id_evictions_started,
            "by_pipeline_run_id_and_background_id",
        )

        spy_logger.info.has_calls(
            [
                [
                    "%s evictions started: %s",
                    "by_pipeline_run_id",
                    by_pipeline_evictions_started,
                ],
                [
                    "%s evictions started: %s",
                    "by_pipeline_run_id_and_background_id",
                    by_pipeline_run_and_background_id_evictions_started,
                ],
            ]
        )

        assert (
            reporter._final_report["evictions_started"]["by_pipeline_run_id"]
            == by_pipeline_evictions_started
        )
        assert (
            reporter._final_report["evictions_started"][
                "by_pipeline_run_id_and_background_id"
            ]
            == by_pipeline_run_and_background_id_evictions_started
        )

    def test_reports_evictions_failed_to_set_task_id(self, mocker):
        spy_logger = mocker.spy(reporter, "logger")

        by_pipeline_evictions_started = [
            {
                "pipeline_run_ids": ["pipeline_run_id_1", "pipeline_run_id_2"],
                "start_eviction_response": {"error": "error"},
                "set_task_id_response": None,
            }
        ]

        by_pipeline_run_and_background_id_evictions_started = [
            {
                "background_id": "1",
                "pipeline_run_ids": ["pipeline_run_id_1", "pipeline_run_id_2"],
                "start_eviction_response": {
                    "error": "error",
                },
                "set_task_id_response": None,
            }
        ]

        reporter.report_evictions_started(
            by_pipeline_evictions_started, "by_pipeline_run_id"
        )
        reporter.report_evictions_started(
            by_pipeline_run_and_background_id_evictions_started,
            "by_pipeline_run_id_and_background_id",
        )

        spy_logger.info.has_calls(
            [
                [
                    "%s evictions started: %s",
                    "by_pipeline_run_id",
                    by_pipeline_evictions_started,
                ],
                [
                    "%s evictions started: %s",
                    "by_pipeline_run_id_and_background_id",
                    by_pipeline_run_and_background_id_evictions_started,
                ],
            ]
        )

        assert (
            reporter._final_report["evictions_started"]["by_pipeline_run_id"]
            == by_pipeline_evictions_started
        )
        assert (
            reporter._final_report["evictions_started"][
                "by_pipeline_run_id_and_background_id"
            ]
            == by_pipeline_run_and_background_id_evictions_started
        )
        assert reporter._final_report["errors"] == [
            {
                "message": "Eviction start failed",
                "details": by_pipeline_evictions_started[0],
            },
            {
                "message": "Eviction start failed",
                "details": by_pipeline_run_and_background_id_evictions_started[0],
            },
        ]

    def test_reports_evictions_failed_to_start(self, mocker):
        spy_logger = mocker.spy(reporter, "logger")

        by_pipeline_evictions_started = [
            {
                "pipeline_run_ids": ["pipeline_run_id_1", "pipeline_run_id_2"],
                "start_eviction_response": {"task": "aaaa-1111-aaaa-1111:1111"},
                "set_task_id_response": {"error": "error"},
            }
        ]

        by_pipeline_run_and_background_id_evictions_started = [
            {
                "background_id": "1",
                "pipeline_run_ids": ["pipeline_run_id_1", "pipeline_run_id_2"],
                "start_eviction_response": {"task": "aaaa-1111-aaaa-1111:1111"},
                "set_task_id_response": {"error": "error"},
            }
        ]

        reporter.report_evictions_started(
            by_pipeline_evictions_started, "by_pipeline_run_id"
        )
        reporter.report_evictions_started(
            by_pipeline_run_and_background_id_evictions_started,
            "by_pipeline_run_id_and_background_id",
        )

        spy_logger.info.has_calls(
            [
                [
                    "%s evictions started: %s",
                    "by_pipeline_run_id",
                    by_pipeline_evictions_started,
                ],
                [
                    "%s evictions started: %s",
                    "by_pipeline_run_id_and_background_id",
                    by_pipeline_run_and_background_id_evictions_started,
                ],
            ]
        )

        assert (
            reporter._final_report["evictions_started"]["by_pipeline_run_id"]
            == by_pipeline_evictions_started
        )
        assert (
            reporter._final_report["evictions_started"][
                "by_pipeline_run_id_and_background_id"
            ]
            == by_pipeline_run_and_background_id_evictions_started
        )
        assert reporter._final_report["errors"] == [
            {
                "message": "Task ID set failed after eviction started",
                "details": by_pipeline_evictions_started[0],
            },
            {
                "message": "Task ID set failed after eviction started",
                "details": by_pipeline_run_and_background_id_evictions_started[0],
            },
        ]
