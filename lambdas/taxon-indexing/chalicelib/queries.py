# type: ignore
# flake8: noqa


def get_scored_taxon_counts_query(pipeline_run_id, background_id):
    """
    Get the scored taxon_counts for the given pipeline/background.
    This query was constructed by referencing the following code:
    old taxon counts query: https://github.com/chanzuckerberg/czid-web-private/blob/8be272/app/services/top_taxons_sql_service.rb#L51-L94
    sample report z-score computation: https://github.com/chanzuckerberg/czid-web-private/blob/8be272/app/services/pipeline_report_service.rb#L684-L741
    """
    return f"""
    SELECT
        -- fields from tables
        taxon_counts.pipeline_run_id,
        taxon_counts.tax_id,
        taxon_counts.count_type,
        taxon_counts.tax_level,
        taxon_counts.genus_taxid,
        taxon_counts.family_taxid,
        taxon_counts.is_phage,
        taxon_counts.counts,
        taxon_counts.percent_identity,
        taxon_counts.alignment_length,
        taxon_counts.e_value,
        taxon_counts.rpm,
        taxon_counts.superkingdom_taxid,
        taxon_counts.`name`,
        taxon_lineages.genus_name,
        taxon_lineages.common_name,
        taxon_summaries.stdev,
        taxon_summaries.mean,
        taxon_summaries.stdev_mass_normalized,
        taxon_summaries.mean_mass_normalized,
        {background_id} AS background_id,
        -- provided and generated fields
        NOW() AS created_at,
        -- computed fields
        COALESCE(
            GREATEST(
                - 99,
                LEAST(
                    99,
                    IF(
                        taxon_summaries.mean_mass_normalized IS NULL,
                        (
                            IF (
                                pipeline_runs.technology = 'Illumina',
                                taxon_counts.rpm,
                                taxon_counts.bpm
                            ) - taxon_summaries.mean
                        ) / taxon_summaries.stdev,
                        IF (
                            pipeline_runs.total_ercc_reads > 0,
                            (
                                (
                                    taxon_counts.counts / 
                                    IF (
                                        pipeline_runs.technology = 'Illumina',
                                        pipeline_runs.total_ercc_reads,
                                        1
                                    )
                                ) - taxon_summaries.mean_mass_normalized
                            ) / taxon_summaries.stdev_mass_normalized,
                            NULL
                        )
                    )
                )
            ),
            100
        ) AS zscore
    FROM
        (
            SELECT
                -- returned
                taxon_counts.pipeline_run_id,
                taxon_counts.tax_id,
                taxon_counts.count_type,
                taxon_counts.tax_level,
                taxon_counts.genus_taxid,
                taxon_counts.family_taxid,
                taxon_counts.superkingdom_taxid,
                taxon_counts.is_phage,
                taxon_counts.`count` AS counts,
                taxon_counts.percent_identity,
                taxon_counts.alignment_length,
                taxon_counts.e_value,
                taxon_counts.rpm,
                taxon_counts.bpm,
                taxon_counts.name,
                -- for joins
                CASE
                    WHEN taxon_counts.tax_id < -100000000
                    THEN -1 * MOD(taxon_counts.tax_id, -100000000)
                    ELSE taxon_counts.tax_id
                END AS lineage_taxon_join_id
            FROM
                taxon_counts
            WHERE pipeline_run_id = '{pipeline_run_id}'
        ) AS taxon_counts
        LEFT OUTER JOIN (
            SELECT
                -- for joins
                pr.id,
                pr.total_ercc_reads,
                pr.technology,
                ac.lineage_version
            FROM
                pipeline_runs pr
                JOIN alignment_configs ac
                    ON ac.id = pr.alignment_config_id
        ) AS pipeline_runs
            ON taxon_counts.pipeline_run_id = pipeline_runs.id
        LEFT OUTER JOIN (
            SELECT
                -- returned
                genus_name,
                family_common_name AS common_name,
                -- for joins
                taxid,
                version_start,
                version_end
            FROM taxon_lineages
        ) AS taxon_lineages
            ON taxon_counts.lineage_taxon_join_id = taxon_lineages.taxid
            AND (taxon_lineages.version_start <= pipeline_runs.lineage_version)
            AND (taxon_lineages.version_end >= pipeline_runs.lineage_version)
        LEFT OUTER JOIN (
            SELECT
                -- returned
                stdev,
                mean,
                stdev_mass_normalized,
                mean_mass_normalized,
                count_type,
                tax_level,
                tax_id,
                background_id
            FROM taxon_summaries
            WHERE background_id = {background_id}
        ) AS taxon_summaries
            ON taxon_counts.count_type = taxon_summaries.count_type
            AND taxon_counts.tax_level = taxon_summaries.tax_level
            AND taxon_counts.tax_id = taxon_summaries.tax_id
    ORDER BY
        tax_id
    """


def get_contigs_by_pipeline_run_id_query(pipeline_run_id):
    """
    Get all contigs for the given pipeline_run_id
    """
    return f"""
    SELECT
        pipeline_run_id,
        species_taxid_nt,
        species_taxid_nr,
        species_taxid_merged_nt_nr,
        genus_taxid_nt,
        genus_taxid_nr,
        genus_taxid_merged_nt_nr
    FROM
        contigs
    WHERE pipeline_run_id = '{pipeline_run_id}' AND lineage_json IS NOT NULL AND lineage_json != '' AND lineage_json != '{{}}'
    """
