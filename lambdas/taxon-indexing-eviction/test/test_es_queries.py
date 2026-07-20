# type: ignore

from chalicelib import es_queries


class TestEsClientResilience:
    def test_client_retries_on_timeout(self, mocker):
        # Node rotation on czid-*-heatmap-es leaves warm containers dialing a dead
        # ENI IP; without retry_on_timeout that connect-timeout fails the whole run.
        # See platform-overhaul #723.
        mocker.patch.object(
            es_queries.config,
            "get_parameters",
            return_value={"ES_HOST": "test-es-host"},
        )
        es_queries.es.cache_clear()

        client = es_queries.es()

        assert client.transport.retry_on_timeout is True
        assert client.transport.max_retries == 3

        es_queries.es.cache_clear()
