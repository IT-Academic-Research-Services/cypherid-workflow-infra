# type: ignore

from chalicelib import change_data_detection


class TestGetPipelineRunsDeletedFromMysql:
    def test_pipelines_deleted(self, mocker):
        mocker.patch.object(
            change_data_detection,
            "get_all_mysql_pipeline_run_ids",
            return_value=["pipeline_run_id_1"],
        )
        mocker.patch.object(
            change_data_detection,
            "get_all_es_pipeline_runs",
            return_value=["pipeline_run_id_1", "pipeline_run_id_2"],
        )

        result = change_data_detection.get_pipeline_runs_deleted_from_mysql()

        assert result == ["pipeline_run_id_2"]

    def test_pipelines_not_deleted(self, mocker):
        mocker.patch.object(
            change_data_detection,
            "get_all_mysql_pipeline_run_ids",
            return_value=["pipeline_run_id_1", "pipeline_run_id_2"],
        )
        mocker.patch.object(
            change_data_detection,
            "get_all_es_pipeline_runs",
            return_value=["pipeline_run_id_1", "pipeline_run_id_2"],
        )

        result = change_data_detection.get_pipeline_runs_deleted_from_mysql()

        assert result == []


class TestGetExpiredPipelinesByBackgroundId:
    def test_no_expired_pipelines(self, mocker):
        mocker.patch.object(
            change_data_detection, "find_expired_pipeline_runs", return_value=[]
        )

        result = change_data_detection.get_expired_pipeline_runs_by_background_id([])

        assert result == {}

    def test_multiple_same_background(self, mocker):
        mocker.patch.object(
            change_data_detection,
            "find_expired_pipeline_runs",
            return_value=[
                {
                    "pipeline_run_id": "pipeline_run_id_1",
                    "background_id": "background_id_1",
                },
                {
                    "pipeline_run_id": "pipeline_run_id_2",
                    "background_id": "background_id_1",
                },
            ],
        )

        result = change_data_detection.get_expired_pipeline_runs_by_background_id([])

        assert result == {"background_id_1": ["pipeline_run_id_1", "pipeline_run_id_2"]}

    def test_exclude_pipelines_being_deleted(self, mocker):
        mocker.patch.object(
            change_data_detection,
            "find_expired_pipeline_runs",
            return_value=[
                {
                    "pipeline_run_id": "pipeline_run_id_1",
                    "background_id": "background_id_1",
                },
                {
                    "pipeline_run_id": "pipeline_run_id_2",
                    "background_id": "background_id_2",
                },
            ],
        )

        result = change_data_detection.get_expired_pipeline_runs_by_background_id(
            ["pipeline_run_id_2"]
        )

        assert result == {"background_id_1": ["pipeline_run_id_1"]}

    def test_exclude_pipelines_being_deleted_single_background(self, mocker):
        mocker.patch.object(
            change_data_detection,
            "find_expired_pipeline_runs",
            return_value=[
                {
                    "pipeline_run_id": "pipeline_run_id_1",
                    "background_id": "background_id_1",
                },
                {
                    "pipeline_run_id": "pipeline_run_id_2",
                    "background_id": "background_id_1",
                },
            ],
        )

        result = change_data_detection.get_expired_pipeline_runs_by_background_id(
            ["pipeline_run_id_2"]
        )

        assert result == {"background_id_1": ["pipeline_run_id_1"]}
