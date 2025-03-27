# type: ignore

from chalicelib import task_management
import test.test_data as test_data


class TestGetDeletionTaskStatuses:
    def test_should_return_running_and_succeeded_task_details(self, mocker):
        mocker.patch.object(
            task_management,
            "get_running_deletion_tasks",
            return_value=test_data.running_tasks,
        )
        mocker.patch.object(
            task_management,
            "get_completed_deletion_tasks",
            return_value=test_data.succeeded_tasks,
        )

        result = task_management.get_deletion_task_statuses(
            test_data.succeeded_pipeline_runs + test_data.running_pipeline_runs
        )

        assert result == {
            "missing_tasks": {"tasks": [], "pipeline_runs": []},
            "running_tasks": {
                "tasks": test_data.running_tasks,
                "pipeline_runs": test_data.running_pipeline_runs,
            },
            "succeeded_tasks": {
                "tasks": test_data.succeeded_tasks,
                "pipeline_runs": test_data.succeeded_pipeline_runs,
            },
            "failed_tasks": {"tasks": [], "pipeline_runs": []},
        }

    def test_should_return_missing_task_details(self, mocker):
        mocker.patch.object(
            task_management, "get_running_deletion_tasks", return_value=[]
        )
        mocker.patch.object(
            task_management, "get_completed_deletion_tasks", return_value=[]
        )

        result = task_management.get_deletion_task_statuses(
            test_data.missing_pipeline_runs
        )

        assert result == {
            "missing_tasks": {
                "tasks": test_data.missing_tasks,
                "pipeline_runs": test_data.missing_pipeline_runs,
            },
            "running_tasks": {"tasks": [], "pipeline_runs": []},
            "succeeded_tasks": {"tasks": [], "pipeline_runs": []},
            "failed_tasks": {"tasks": [], "pipeline_runs": []},
        }

    def test_should_return_failed_task_details(self, mocker):
        mocker.patch.object(
            task_management, "get_running_deletion_tasks", return_value=[]
        )
        mocker.patch.object(
            task_management,
            "get_completed_deletion_tasks",
            return_value=test_data.failed_tasks,
        )

        result = task_management.get_deletion_task_statuses(
            test_data.failed_pipeline_runs
        )
        assert result == {
            "missing_tasks": {"tasks": [], "pipeline_runs": []},
            "running_tasks": {"tasks": [], "pipeline_runs": []},
            "succeeded_tasks": {"tasks": [], "pipeline_runs": []},
            "failed_tasks": {
                "tasks": test_data.failed_tasks,
                "pipeline_runs": test_data.failed_pipeline_runs,
            },
        }


class TestCleanupExistingTasks:
    def test_should_dry_run(self):
        result = task_management.cleanup_existing_tasks(
            test_data.task_statuses, dry_run=True
        )

        assert result == (
            1,
            test_data.running_pipeline_runs + test_data.succeeded_pipeline_runs
        )

    def test_should_non_dry_run(self, mocker):
        mocker.patch.object(
            task_management, "delete_tasks", return_value={"success": True}
        )
        mocker.patch.object(
            task_management, "bulk_delete_pipeline_runs", return_value={"success": True}
        )

        result = task_management.cleanup_existing_tasks(
            test_data.task_statuses, dry_run=False
        )

        assert result == (
            1,
            test_data.running_pipeline_runs + test_data.succeeded_pipeline_runs
        )


class TestCheckCapacity:
    def test_should_return_zero_if_capacity_is_negative(self, mocker):
        mocker.patch.object(
            task_management,
            "get_parameters",
            return_value={"EVICTION_TASK_CONCURRENCY": 1},
        )

        assert task_management.check_capacity(2) == 0

    def test_should_return_capacity(self, mocker):
        mocker.patch.object(
            task_management,
            "get_parameters",
            return_value={"EVICTION_TASK_CONCURRENCY": 2},
        )

        assert task_management.check_capacity(1) == 1


class TestDiscoverEvictionCandidates:
    def test_should_return_eviction_candidates(self, mocker):
        mocker.patch.object(
            task_management,
            "get_pipeline_runs_deleted_from_mysql",
            return_value=["pipeline_run_id_1", "pipeline_run_id_5"],
        )
        mocker.patch.object(
            task_management,
            "get_expired_pipeline_runs_by_background_id",
            return_value={
                "background_id_1": ["pipeline_run_id_6"],
            },
        )

        result = task_management.discover_eviction_candidates(
            ["pipeline_run_id_1", "pipeline_run_id_2"],
        )

        assert result == (
            ["pipeline_run_id_5"],
            {
                "background_id_1": ["pipeline_run_id_6"],
            },
        )


class TestEvictByPipelineRunIds:
    def test_should_return_single_batch(self, mocker):
        mocker.patch.object(
            task_management,
            "get_parameters",
            return_value={"PIPELINE_RUNS_PER_TASK": 2},
        )
        mocker.patch.object(
            task_management,
            "bulk_delete_taxons_by_pipeline_run_id",
            return_value={"task": "aaaa-1111-aaaa-1111:1111"},
        )
        mocker.patch.object(
            task_management,
            "set_task_id_on_pipelines_being_deleted",
            return_value={"success": True},
        )
        mocker.patch.object(
            task_management, "report_evictions_started", return_value=None
        )
        spy_bulk_delete_taxons_by_pipeline_run_id = mocker.spy(
            task_management, "bulk_delete_taxons_by_pipeline_run_id"
        )
        spy_set_task_id_on_pipelines_being_deleted = mocker.spy(
            task_management, "set_task_id_on_pipelines_being_deleted"
        )
        spy_report_evictions_started = mocker.spy(
            task_management, "report_evictions_started"
        )

        result = task_management.evict_by_pipeline_run_ids(
            ["pipeline_run_id_1", "pipeline_run_id_2"], 2
        )

        assert result == 1
        spy_bulk_delete_taxons_by_pipeline_run_id.assert_called_once_with(
            ["pipeline_run_id_1", "pipeline_run_id_2"]
        )
        spy_set_task_id_on_pipelines_being_deleted.assert_called_once_with(
            "aaaa-1111-aaaa-1111:1111", ["pipeline_run_id_1", "pipeline_run_id_2"]
        )
        spy_report_evictions_started.assert_called_once_with(
            [
                {
                    "pipeline_run_ids": ["pipeline_run_id_1", "pipeline_run_id_2"],
                    "start_eviction_response": {"task": "aaaa-1111-aaaa-1111:1111"},
                    "set_task_id_response": {"success": True},
                }
            ],
            "by_pipeline_run_id",
        )

    def test_should_return_multiple_batch(self, mocker):
        mocker.patch.object(
            task_management,
            "get_parameters",
            return_value={"PIPELINE_RUNS_PER_TASK": 1},
        )
        mocker.patch.object(
            task_management,
            "bulk_delete_taxons_by_pipeline_run_id",
            return_value={"task": "aaaa-1111-aaaa-1111:1111"},
        )
        mocker.patch.object(
            task_management,
            "set_task_id_on_pipelines_being_deleted",
            return_value={"success": True},
        )
        mocker.patch.object(
            task_management, "report_evictions_started", return_value=None
        )
        spy_bulk_delete_taxons_by_pipeline_run_id = mocker.spy(
            task_management, "bulk_delete_taxons_by_pipeline_run_id"
        )
        spy_set_task_id_on_pipelines_being_deleted = mocker.spy(
            task_management, "set_task_id_on_pipelines_being_deleted"
        )
        spy_report_evictions_started = mocker.spy(
            task_management, "report_evictions_started"
        )

        result = task_management.evict_by_pipeline_run_ids(
            ["pipeline_run_id_1", "pipeline_run_id_2"], 2
        )

        assert result == 0
        spy_bulk_delete_taxons_by_pipeline_run_id.has_calls(
            [["pipeline_run_id_1"], ["pipeline_run_id_2"]]
        )
        spy_set_task_id_on_pipelines_being_deleted.has_calls(
            ["aaaa-1111-aaaa-1111:1111", ["pipeline_run_id_1"]],
            ["aaaa-1111-aaaa-1111:1111", ["pipeline_run_id_2"]],
        )
        spy_report_evictions_started.assert_called_once_with(
            [
                {
                    "pipeline_run_ids": ["pipeline_run_id_1"],
                    "start_eviction_response": {"task": "aaaa-1111-aaaa-1111:1111"},
                    "set_task_id_response": {"success": True},
                },
                {
                    "pipeline_run_ids": ["pipeline_run_id_2"],
                    "start_eviction_response": {"task": "aaaa-1111-aaaa-1111:1111"},
                    "set_task_id_response": {"success": True},
                },
            ],
            "by_pipeline_run_id",
        )

    def test_should_stop_at_capacity(self, mocker):
        mocker.patch.object(
            task_management,
            "get_parameters",
            return_value={"PIPELINE_RUNS_PER_TASK": 1},
        )
        mocker.patch.object(
            task_management,
            "bulk_delete_taxons_by_pipeline_run_id",
            return_value={"task": "aaaa-1111-aaaa-1111:1111"},
        )
        mocker.patch.object(
            task_management,
            "set_task_id_on_pipelines_being_deleted",
            return_value={"success": True},
        )
        mocker.patch.object(
            task_management, "report_evictions_started", return_value=None
        )
        spy_bulk_delete_taxons_by_pipeline_run_id = mocker.spy(
            task_management, "bulk_delete_taxons_by_pipeline_run_id"
        )
        spy_set_task_id_on_pipelines_being_deleted = mocker.spy(
            task_management, "set_task_id_on_pipelines_being_deleted"
        )
        spy_report_evictions_started = mocker.spy(
            task_management, "report_evictions_started"
        )

        result = task_management.evict_by_pipeline_run_ids(
            ["pipeline_run_id_1", "pipeline_run_id_2"], 1
        )

        assert result == 0
        spy_bulk_delete_taxons_by_pipeline_run_id.assert_called_once_with(
            ["pipeline_run_id_1"]
        )
        spy_set_task_id_on_pipelines_being_deleted.assert_called_once_with(
            "aaaa-1111-aaaa-1111:1111", ["pipeline_run_id_1"]
        )
        spy_report_evictions_started.assert_called_once_with(
            [
                {
                    "pipeline_run_ids": ["pipeline_run_id_1"],
                    "start_eviction_response": {"task": "aaaa-1111-aaaa-1111:1111"},
                    "set_task_id_response": {"success": True},
                }
            ],
            "by_pipeline_run_id",
        )


class TestEvictByPipelineAndBackgroundId:
    def test_should_return_single_batch(self, mocker):
        mocker.patch.object(
            task_management,
            "get_parameters",
            return_value={"PIPELINE_RUNS_PER_TASK": 2},
        )
        mocker.patch.object(
            task_management,
            "bulk_delete_taxons_by_pipeline_run_id_and_background_id",
            return_value={"task": "aaaa-1111-aaaa-1111:1111"},
        )
        mocker.patch.object(
            task_management,
            "set_task_id_on_pipelines_backgrounds_being_deleted",
            return_value={"success": True},
        )
        mocker.patch.object(
            task_management, "report_evictions_started", return_value=None
        )
        spy_bulk_delete_taxons_by_pipeline_run_id_and_background_id = mocker.spy(
            task_management, "bulk_delete_taxons_by_pipeline_run_id_and_background_id"
        )
        spy_set_task_id_on_pipelines_backgrounds_being_deleted = mocker.spy(
            task_management, "set_task_id_on_pipelines_backgrounds_being_deleted"
        )
        spy_report_evictions_started = mocker.spy(
            task_management, "report_evictions_started"
        )

        result = task_management.evict_by_pipeline_and_background_id(
            {"1": ["pipeline_run_id_1", "pipeline_run_id_2"]}, 2
        )

        assert result == 1
        spy_bulk_delete_taxons_by_pipeline_run_id_and_background_id.assert_called_once_with(
            "1", ["pipeline_run_id_1", "pipeline_run_id_2"]
        )
        spy_set_task_id_on_pipelines_backgrounds_being_deleted.assert_called_once_with(
            "aaaa-1111-aaaa-1111:1111", "1", ["pipeline_run_id_1", "pipeline_run_id_2"]
        )
        spy_report_evictions_started.assert_called_once_with(
            [
                {
                    "background_id": "1",
                    "pipeline_run_ids": ["pipeline_run_id_1", "pipeline_run_id_2"],
                    "start_eviction_response": {"task": "aaaa-1111-aaaa-1111:1111"},
                    "set_task_id_response": {"success": True},
                }
            ],
            "by_pipeline_run_id_and_background_id",
        )

    def test_should_return_multiple_batch(self, mocker):
        mocker.patch.object(
            task_management,
            "get_parameters",
            return_value={"PIPELINE_RUNS_PER_TASK": 1},
        )
        mocker.patch.object(
            task_management,
            "bulk_delete_taxons_by_pipeline_run_id_and_background_id",
            return_value={"task": "aaaa-1111-aaaa-1111:1111"},
        )
        mocker.patch.object(
            task_management,
            "set_task_id_on_pipelines_backgrounds_being_deleted",
            return_value={"success": True},
        )
        mocker.patch.object(
            task_management, "report_evictions_started", return_value=None
        )
        spy_bulk_delete_taxons_by_pipeline_run_id_and_background_id = mocker.spy(
            task_management, "bulk_delete_taxons_by_pipeline_run_id_and_background_id"
        )
        spy_set_task_id_on_pipelines_backgrounds_being_deleted = mocker.spy(
            task_management, "set_task_id_on_pipelines_backgrounds_being_deleted"
        )
        spy_report_evictions_started = mocker.spy(
            task_management, "report_evictions_started"
        )

        result = task_management.evict_by_pipeline_and_background_id(
            {"1": ["pipeline_run_id_1", "pipeline_run_id_2"]}, 2
        )

        assert result == 0
        spy_bulk_delete_taxons_by_pipeline_run_id_and_background_id.has_calls(
            ["1", ["pipeline_run_id_1"]], ["1", ["pipeline_run_id_2"]]
        )
        spy_set_task_id_on_pipelines_backgrounds_being_deleted.has_calls(
            ["aaaa-1111-aaaa-1111:1111", "1", ["pipeline_run_id_1"]],
            ["aaaa-1111-aaaa-1111:1111", "1", ["pipeline_run_id_2"]],
        )
        spy_report_evictions_started.assert_called_once_with(
            [
                {
                    "background_id": "1",
                    "pipeline_run_ids": ["pipeline_run_id_1"],
                    "start_eviction_response": {"task": "aaaa-1111-aaaa-1111:1111"},
                    "set_task_id_response": {"success": True},
                },
                {
                    "background_id": "1",
                    "pipeline_run_ids": ["pipeline_run_id_2"],
                    "start_eviction_response": {"task": "aaaa-1111-aaaa-1111:1111"},
                    "set_task_id_response": {"success": True},
                },
            ],
            "by_pipeline_run_id_and_background_id",
        )

    def test_should_return_multiple_batch_across_backgrounds(self, mocker):
        mocker.patch.object(
            task_management,
            "get_parameters",
            return_value={"PIPELINE_RUNS_PER_TASK": 1},
        )
        mocker.patch.object(
            task_management,
            "bulk_delete_taxons_by_pipeline_run_id_and_background_id",
            return_value={"task": "aaaa-1111-aaaa-1111:1111"},
        )
        mocker.patch.object(
            task_management,
            "set_task_id_on_pipelines_backgrounds_being_deleted",
            return_value={"success": True},
        )
        mocker.patch.object(
            task_management, "report_evictions_started", return_value=None
        )
        spy_bulk_delete_taxons_by_pipeline_run_id_and_background_id = mocker.spy(
            task_management, "bulk_delete_taxons_by_pipeline_run_id_and_background_id"
        )
        spy_set_task_id_on_pipelines_backgrounds_being_deleted = mocker.spy(
            task_management, "set_task_id_on_pipelines_backgrounds_being_deleted"
        )
        spy_report_evictions_started = mocker.spy(
            task_management, "report_evictions_started"
        )

        result = task_management.evict_by_pipeline_and_background_id(
            {"1": ["pipeline_run_id_1"], "2": ["pipeline_run_id_2"]}, 2
        )

        assert result == 0
        spy_bulk_delete_taxons_by_pipeline_run_id_and_background_id.has_calls(
            ["1", ["pipeline_run_id_1"]], ["2", ["pipeline_run_id_2"]]
        )
        spy_set_task_id_on_pipelines_backgrounds_being_deleted.has_calls(
            ["aaaa-1111-aaaa-1111:1111", "1", ["pipeline_run_id_1"]],
            ["aaaa-1111-aaaa-1111:1111", "2", ["pipeline_run_id_2"]],
        )
        spy_report_evictions_started.assert_called_once_with(
            [
                {
                    "background_id": "1",
                    "pipeline_run_ids": ["pipeline_run_id_1"],
                    "start_eviction_response": {"task": "aaaa-1111-aaaa-1111:1111"},
                    "set_task_id_response": {"success": True},
                },
                {
                    "background_id": "2",
                    "pipeline_run_ids": ["pipeline_run_id_2"],
                    "start_eviction_response": {"task": "aaaa-1111-aaaa-1111:1111"},
                    "set_task_id_response": {"success": True},
                },
            ],
            "by_pipeline_run_id_and_background_id",
        )

    def test_should_stop_at_capacity(self, mocker):
        mocker.patch.object(
            task_management,
            "get_parameters",
            return_value={"PIPELINE_RUNS_PER_TASK": 1},
        )
        mocker.patch.object(
            task_management,
            "bulk_delete_taxons_by_pipeline_run_id_and_background_id",
            return_value={"task": "aaaa-1111-aaaa-1111:1111"},
        )
        mocker.patch.object(
            task_management,
            "set_task_id_on_pipelines_backgrounds_being_deleted",
            return_value={"success": True},
        )
        mocker.patch.object(
            task_management, "report_evictions_started", return_value=None
        )
        spy_bulk_delete_taxons_by_pipeline_run_id_and_background_id = mocker.spy(
            task_management, "bulk_delete_taxons_by_pipeline_run_id_and_background_id"
        )
        spy_set_task_id_on_pipelines_backgrounds_being_deleted = mocker.spy(
            task_management, "set_task_id_on_pipelines_backgrounds_being_deleted"
        )
        spy_report_evictions_started = mocker.spy(
            task_management, "report_evictions_started"
        )

        result = task_management.evict_by_pipeline_and_background_id(
            {"1": ["pipeline_run_id_1", "pipeline_run_id_2"]}, 1
        )

        assert result == 0
        spy_bulk_delete_taxons_by_pipeline_run_id_and_background_id.assert_called_once_with(
            "1", ["pipeline_run_id_1"]
        )
        spy_set_task_id_on_pipelines_backgrounds_being_deleted.assert_called_once_with(
            "aaaa-1111-aaaa-1111:1111", "1", ["pipeline_run_id_1"]
        )
        spy_report_evictions_started.assert_called_once_with(
            [
                {
                    "background_id": "1",
                    "pipeline_run_ids": ["pipeline_run_id_1"],
                    "start_eviction_response": {"task": "aaaa-1111-aaaa-1111:1111"},
                    "set_task_id_response": {"success": True},
                },
            ],
            "by_pipeline_run_id_and_background_id",
        )

    def test_should_stop_at_capacity_across_backgrounds(self, mocker):
        mocker.patch.object(
            task_management,
            "get_parameters",
            return_value={"PIPELINE_RUNS_PER_TASK": 1},
        )
        mocker.patch.object(
            task_management,
            "bulk_delete_taxons_by_pipeline_run_id_and_background_id",
            return_value={"task": "aaaa-1111-aaaa-1111:1111"},
        )
        mocker.patch.object(
            task_management,
            "set_task_id_on_pipelines_backgrounds_being_deleted",
            return_value={"success": True},
        )
        mocker.patch.object(
            task_management, "report_evictions_started", return_value=None
        )
        spy_bulk_delete_taxons_by_pipeline_run_id_and_background_id = mocker.spy(
            task_management, "bulk_delete_taxons_by_pipeline_run_id_and_background_id"
        )
        spy_set_task_id_on_pipelines_backgrounds_being_deleted = mocker.spy(
            task_management, "set_task_id_on_pipelines_backgrounds_being_deleted"
        )
        spy_report_evictions_started = mocker.spy(
            task_management, "report_evictions_started"
        )

        result = task_management.evict_by_pipeline_and_background_id(
            {
                "1": ["pipeline_run_id_1"],
                "2": ["pipeline_run_id_2"],
            },
            1,
        )

        assert result == 0
        spy_bulk_delete_taxons_by_pipeline_run_id_and_background_id.assert_called_once_with(
            "1", ["pipeline_run_id_1"]
        )
        spy_set_task_id_on_pipelines_backgrounds_being_deleted.assert_called_once_with(
            "aaaa-1111-aaaa-1111:1111", "1", ["pipeline_run_id_1"]
        )
        spy_report_evictions_started.assert_called_once_with(
            [
                {
                    "background_id": "1",
                    "pipeline_run_ids": ["pipeline_run_id_1"],
                    "start_eviction_response": {"task": "aaaa-1111-aaaa-1111:1111"},
                    "set_task_id_response": {"success": True},
                },
            ],
            "by_pipeline_run_id_and_background_id",
        )


class TestBatches:
    def test_empty_list(self):
        result = task_management.batches([], 2)

        assert list(result) == []

    def test_single_item(self):
        result = task_management.batches([1], 2)

        assert list(result) == [[1]]

    def test_multiple_even_items(self):
        result = task_management.batches([1, 2, 3, 4], 2)

        assert list(result) == [[1, 2], [3, 4]]

    def test_multiple_odd_items(self):
        result = task_management.batches([1, 2, 3, 4, 5], 2)

        assert list(result) == [[1, 2], [3, 4], [5]]
