import argparse
import gzip
import json
import re
from datetime import datetime
from glob import glob
from os.path import join, basename
from tempfile import NamedTemporaryFile
from typing import Iterable, Union
from urllib.parse import urlparse

import boto3
import requests

from simple_run_sfn import simple_run_sfn


REFERENCES_BUCKET = 'czid-public-references'


sts = boto3.client('sts')
s3 = boto3.resource('s3')
s3_client = boto3.client('s3')


parser = argparse.ArgumentParser(description="Script for generating host genomes")
subparsers = parser.add_subparsers(help='Commands', dest='command')


parser_generate = subparsers.add_parser('generate', help='Kick off the host genome generation job')
parser_generate.add_argument(
    '-n',
    '--host-name',
    help='Name for the host, for internal use, must be snake case',
    metavar='bank_vole',
    required=True,
)
parser_generate.add_argument(
    '-r',
    '--readme',
    help='Path to a readme file for this host genome, should contain information about where the genome came from and when it was generated',
    metavar='README.md',
    required=True,
)
parser_generate.add_argument(
    '-f',
    '--input-fasta',
    help='Path to an input fasta, fa, or fna file for the host genome',
    metavar='organism.fna',
    required=True,
)
parser_generate.add_argument(
    '-a',
    '--additional-fastas',
    help='Glob of additional fastas to include in the host genome (optional)',
    metavar='*/organism.fna',
    default=None,
)
parser_generate.add_argument(
    '-t',
    '--transcript-fastas',
    help='Glob of transcript fastas, nescessary for host genome counts, obtain from NCBI (optional)',
    metavar='*/rna.fna',
    default=None
)
parser_generate.add_argument(
    '-g',
    '--input-gtf',
    help='Path to an input gtf file for the host genome (optional)',
    metavar='organism.gtf',
    default=None,
)


parser_prerelease = subparsers.add_parser('prerelease', help='Prepare this host genome for release and generate a migration to add it to the database')
parser_prerelease.add_argument(
    '-n',
    '--host-name',
    help="Name for the host, for internal use, must be snake case",
    metavar='bank_vole',
    required=True,
)
parser_prerelease.add_argument(
    '-u',
    '--user-host-name',
    help='Name for the host, visible to the user, should be title case',
    metavar="'Bank Vole'",
    required=True,
)
parser_prerelease.add_argument(
    '-c',
    '--czid-web-private-repo',
    help='Local czid-web-private repo, to deposit auto-generated migration',
    metavar='~/czid-web-private',
    required=True,
)
# string argument instead of boolean so we can explicitly require it
parser_prerelease.add_argument(
    '-d',
    '--is-deuterostome',
    help='Is the host a deuterostome? https://en.wikipedia.org/wiki/Deuterostome',
    choices=['yes', 'no'],
    required=True,
)


def _tags():
    url = 'https://api.github.com/repos/chanzuckerberg/czid-workflows/tags'
    while url:
        resp = requests.get(url)
        for tag in resp.json():
            yield str(tag['name'])
        url = resp.links.get('next', {}).get('url')


def _is_gzipped(filename): 
    with open(filename, 'rb') as f:
        return f.read(2) == b'\x1f\x8b'


def generate_host_genome(
    host_name: str,
    readme: str,
    input_fasta: str,
    additional_fastas: Iterable[str] = [],
    transcript_fastas: Iterable[str] = [],
    input_gtf: Union[str, None] = None,
):
    assert re.match(r'^[a-z-_]+$', host_name), "host_name must be in snake case"

    day_slug = datetime.now().strftime('%Y-%m-%d')
    s3_prefix = f's3://{REFERENCES_BUCKET}/host_filter/{host_name}/{day_slug}/'

    def _upload_to_s3_path_public(filename: str, object_name: Union[str, None] = None, gzip_file=True):
        _object_name = object_name or basename(filename)
        if gzip_file or _is_gzipped(filename) and not object_name.endswith('.gz'):
            _object_name += '.gz'
        s3_path = join(s3_prefix, object_name or basename(filename))
        print(f'uploading {filename} to {s3_path}')
        parsed = urlparse(s3_path)
        bucket, key = parsed.hostname, parsed.path[1:]
        if not gzip_file or _is_gzipped(filename):
            s3.Bucket(bucket).upload_file(filename, key)
        else:
            with NamedTemporaryFile('wb') as f:
                with open(filename, 'rb') as f_read, gzip.open(f.name, 'wb') as f_write:
                    f_write.writelines(f_read)
                f.seek(0)
                s3.Bucket(bucket).upload_file(f.name, key)
        s3.ObjectAcl(bucket, key).put(ACL='public-read')
        print(f'uploaded {filename} to {s3_path}')
        return s3_path


    _upload_to_s3_path_public(readme, "README.md", False)

    tag = next(tag for tag in _tags() if tag.startswith('host-genome-generation'))
    version = tag.replace('host-genome-generation-v', '')
    print(f'using host-genome-generation workflow version: {version}')

    wdl_input = {
        'genome_name': host_name,
        'ERCC_fasta_gz': f's3://{REFERENCES_BUCKET}/host_filter/ercc/2018-02-15-utc-1518652800-unixtime__2018-02-15-utc-1518652800-unixtime/ERCC.fa.gz',
        'genome_fasta_gz': _upload_to_s3_path_public(input_fasta),
        'transcripts_fasta_gz': [_upload_to_s3_path_public(f) for f in transcript_fastas],
        'other_fasta_gz': [_upload_to_s3_path_public(f) for f in additional_fastas],
    }

    if input_gtf:
        wdl_input['transcripts_gtf_gz'] = _upload_to_s3_path_public(input_gtf)

    print('generating, this may take a while, feel free to interrupt it wil continue in AWS')

    simple_run_sfn(
        "host-genome-generation",
        version,
        s3_prefix,
        "prod",
        wdl_input,
        watch=True,
        s3_wd_uri=False,
        memory=int(7e5),
    )


def prerelease_host_genome(host_name: str, user_facing_host_name: str, czid_web_private_repo: str, is_deuterostome: bool):
    res = s3_client.list_objects_v2(Bucket=REFERENCES_BUCKET, Prefix=f'host_filter/{host_name}/')
    most_recent_outfile = [obj['Key'] for obj in res['Contents'] if obj['Key'].endswith('run_output.json')][-1]

    outputs = json.loads(s3.Bucket(REFERENCES_BUCKET).Object(most_recent_outfile).get()["Body"].read())
    output_keys = { k: urlparse(v).path[1:] for k, v in outputs.items() if v and type(v) == str }

    print('making index public')
    for s3_key in output_keys.values():
        s3.ObjectAcl(REFERENCES_BUCKET, s3_key).put(ACL='public-read')

    migration_slug = f'add_host_genome_{host_name}'
    migration_classname = ''.join(w.title() for w in migration_slug.split('_'))
    migration_filename = f'{datetime.now().strftime("%Y%m%d%H%M%S")}_{migration_slug}.rb'

    S3_DATABASE_BUCKET = '{S3_DATABASE_BUCKET}'

    migration = f"""
# frozen_string_literal: true

# Generated by https://github.com/chanzuckerberg/idseq/blob/main/scripts/generate_host_genome.py

class {migration_classname} < ActiveRecord::Migration[6.1]
  def up
    return if HostGenome.find_by(name: "{user_facing_host_name}")

    hg = HostGenome.new
    hg.name = "{user_facing_host_name}"
    hg.s3_star_index_path = "s3://#{S3_DATABASE_BUCKET}/{output_keys['host_filter_indexing.star_genome_tar']}"
    hg.s3_bowtie2_index_path = "s3://#{S3_DATABASE_BUCKET}/{output_keys['host_filter_indexing.bowtie2_index_tar']}"
    hg.s3_minimap2_dna_index_path = "s3://#{S3_DATABASE_BUCKET}/{output_keys['host_filter_indexing.minimap2_dna_mmi']}"
    hg.s3_minimap2_rna_index_path = "s3://#{S3_DATABASE_BUCKET}/{output_keys['host_filter_indexing.minimap2_rna_mmi']}"
    hg.s3_hisat2_index_path = "s3://#{S3_DATABASE_BUCKET}/{output_keys['host_filter_indexing.hisat2_index_tar']}"
    hg.s3_kallisto_index_path = "s3://#{S3_DATABASE_BUCKET}/{output_keys['host_filter_indexing.kallisto_idx']}"
    hg.s3_bowtie2_index_path_v2 = "s3://#{S3_DATABASE_BUCKET}/{output_keys['host_filter_indexing.bowtie2_index_tar']}"
    hg.skip_deutero_filter = {1 if is_deuterostome else 0} # this is set to {1 if is_deuterostome else 0} because the host is{'' if is_deuterostome else ' not'} a deuterostome

    hg.default_background_id = nil
    hg.save!
  end

  def down
    hg = HostGenome.find_by(name: "{user_facing_host_name}")
    hg.destroy! if hg
  end
end"""[1:]

    migration_output_path = join(czid_web_private_repo, 'db/data', migration_filename)
    print(f'saving migration to: {migration_output_path}')
    with open(migration_output_path, 'w') as f:
        f.write(migration)


if __name__ == '__main__':
    assert sts.get_caller_identity()['Account'] == '745463180746', 'you must run this on the production account'

    args = parser.parse_args()

    if args.command == 'generate':
        additional_fastas = glob(args.additional_fastas) if args.additional_fastas else []
        transcript_fastas = glob(args.transcript_fastas) if args.transcript_fastas else []
        generate_host_genome(args.host_name, args.readme, args.input_fasta, additional_fastas, transcript_fastas, args.input_gtf)
    elif args.command == 'prerelease':
        prerelease_host_genome(args.host_name, args.user_host_name, args.czid_web_private_repo, args.is_deuterostome == 'yes')
