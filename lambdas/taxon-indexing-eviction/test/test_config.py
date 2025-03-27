# type: ignore

from chalicelib import config


class TestGetParameters:
    def test_params_in_env(self, mocker):
        mocker.patch.dict(
            "os.environ",
            {
                "MYSQL_HOST": "test-mysql-host",
                "MYSQL_PORT": "test-mysql-port",
                "MYSQL_DB": "test-mysql-db",
                "MYSQL_USERNAME": "test-mysql-username",
                "MYSQL_PASSWORD": "test-mysql-password",
                "ES_HOST": "test-es-host",
                "DELETE_REQUESTS_PER_SECOND": "99",
                "EVICTION_TASK_CONCURRENCY": "98",
                "PIPELINE_RUNS_PER_TASK": "97",
                "PIPELINE_RUN_TTL_IN_DAYS": "96",
                "DRY_RUN": "True"
            },
            clear=True,
        )
        mocker.patch.object(config, "_get_params_from_ssm", return_value={})
        ssm_spy = mocker.spy(config, "_get_params_from_ssm")

        config.get_parameters.cache_clear()
        assert config.get_parameters() == {
            "MYSQL_HOST": "test-mysql-host",
            "MYSQL_PORT": "test-mysql-port",
            "MYSQL_DB": "test-mysql-db",
            "MYSQL_USERNAME": "test-mysql-username",
            "MYSQL_PASSWORD": "test-mysql-password",
            "ES_HOST": "test-es-host",
            "DELETE_REQUESTS_PER_SECOND": 99,
            "EVICTION_TASK_CONCURRENCY": 98,
            "PIPELINE_RUNS_PER_TASK": 97,
            "PIPELINE_RUN_TTL_IN_DAYS": 96,
            "DRY_RUN": True
        }

        ssm_spy.assert_not_called()

    def test_params_default(self, mocker):
        mocker.patch.dict(
            "os.environ",
            {
                "MYSQL_HOST": "test-mysql-host",
                "MYSQL_PORT": "test-mysql-port",
                "MYSQL_USERNAME": "test-mysql-username",
                "MYSQL_PASSWORD": "test-mysql-password",
                "ES_HOST": "test-es-host"
            },
            clear=True,
        )
        mocker.patch.object(config, "_get_params_from_ssm", return_value={})
        ssm_spy = mocker.spy(config, "_get_params_from_ssm")

        config.get_parameters.cache_clear()
        assert config.get_parameters() == {
            "MYSQL_HOST": "test-mysql-host",
            "MYSQL_PORT": "test-mysql-port",
            "MYSQL_DB": "idseq_test",
            "MYSQL_USERNAME": "test-mysql-username",
            "MYSQL_PASSWORD": "test-mysql-password",
            "ES_HOST": "test-es-host",
            "DELETE_REQUESTS_PER_SECOND": 100,
            "EVICTION_TASK_CONCURRENCY": 2,
            "PIPELINE_RUNS_PER_TASK": 200,
            "PIPELINE_RUN_TTL_IN_DAYS": 30,
            "DRY_RUN": False
        }

        ssm_spy.assert_not_called()

    def test_params_from_ssm(self, mocker):
        mocker.patch.dict(
            "os.environ",
            {
                "MYSQL_HOST": "test-mysql-host",
                "MYSQL_PORT": "test-mysql-port",
                "MYSQL_USERNAME": "test-mysql-username",
                "MYSQL_PASSWORD": "test-mysql-password",
                "ES_HOST": "test-es-host",
            },
            clear=True,
        )
        mocker.patch.object(
            config,
            "_get_params_from_ssm",
            return_value={
                "MYSQL_HOST": "ssm-mysql-db",
                "MYSQL_PORT": "ssm-mysql-port",
                "MYSQL_USERNAME": "ssm-mysql-username",
                "MYSQL_PASSWORD": "ssm-mysql-password",
                "ES_HOST": "ssm-es-host",
            },
        )
        ssm_spy = mocker.spy(config, "_get_params_from_ssm")

        config.get_parameters.cache_clear()
        assert config.get_parameters() == {
            "MYSQL_HOST": "test-mysql-host",
            "MYSQL_PORT": "test-mysql-port",
            "MYSQL_DB": "idseq_test",
            "MYSQL_USERNAME": "test-mysql-username",
            "MYSQL_PASSWORD": "test-mysql-password",
            "ES_HOST": "test-es-host",
            "DELETE_REQUESTS_PER_SECOND": 100,
            "EVICTION_TASK_CONCURRENCY": 2,
            "PIPELINE_RUNS_PER_TASK": 200,
            "PIPELINE_RUN_TTL_IN_DAYS": 30,
            "DRY_RUN": False
        }

        ssm_spy.assert_not_called()
