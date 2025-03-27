build:
	rm -rf ./dist && mkdir ./dist
	cp ./main.py ./dist
	cp ./config.py ./dist
	cp ./job.py ./dist

sandbox-deploy: build
	aws s3 cp dist s3://idseq-sandbox-heatmap-batch-jobs/releases --recursive --profile idseq-dev

staging-deploy: build
	aws s3 cp dist s3://idseq-staging-heatmap-batch-jobs/releases --recursive --profile idseq-dev

prod-deploy: build
	aws s3 cp dist s3://idseq-prod-heatmap-batch-jobs/releases --recursive --profile idseq-prod

trigger-sandbox:
	if [ -z "$(INPUT_FILE)" ]; then \
		echo "usage: INPUT_FILE=input_file_name make trigger-sandbox"; \
	else \
		aws glue start-job-run \
			--job-name idseq-sandbox-batch-taxon-indexing \
			--profile idseq-dev \
			--arguments '{"--input_s3_path": "input_files/$(INPUT_FILE)", "--scored_taxon_counts_index_name": "scored_taxon_counts-reindex-test", "--pipeline_runs_index_name": "pipeline_runs-reindex-test"}'; \
	fi

trigger-staging:
	if [ -z "$(INPUT_FILE)" ]; then \
		echo "usage: INPUT_FILE=input_file_name make trigger-sandbox"; \
	else \
		aws glue start-job-run \
			--job-name idseq-staging-batch-taxon-indexing \
			--profile idseq-dev \
			--arguments '{"--input_s3_path": "input_files/$(INPUT_FILE)", "--scored_taxon_counts_index_name": "scored_taxon_counts-reindex-test", "--pipeline_runs_index_name": "pipeline_runs-reindex-test"}'; \
	fi

trigger-prod:
	if [ -z "$(INPUT_FILE)" ]; then \
		echo "usage: INPUT_FILE=input_file_name make trigger-sandbox"; \
	else \
		aws glue start-job-run \
			--job-name idseq-prod-batch-taxon-indexing \
			--profile idseq-prod \
			--arguments '{"--input_s3_path": "input_files/$(INPUT_FILE)", "--scored_taxon_counts_index_name": "scored_taxon_counts-v5", "--pipeline_runs_index_name": "pipeline_runs-v5"}'; \
	fi