import json
import logging
import os
import sys
from multiprocessing import Pool
from os.path import join
from string import Template
from subprocess import run


logging.basicConfig(level=logging.INFO)


def package_lambda(name: str):
    deployment_environment = os.environ['DEPLOYMENT_ENVIRONMENT']
    lambda_dir = join('lambdas', name)
    chalice_config_path = join(lambda_dir, '.chalice/config.json')
    using_chalice = os.path.exists(chalice_config_path)
    policy_template_path = join(lambda_dir, 'policy-template.json')
    policy_output_path = join(lambda_dir, f'.chalice/policy-{deployment_environment}.json')
    docker_tag = f'{name}-package'
    output_dir = join('terraform', 'modules', name)
    terraform_json_path = join(output_dir, 'chalice.tf.json')

    if using_chalice:
        logging.info(f'packaging chalice lambda: {lambda_dir}')
    else:
        logging.info(f'packing lambda: {lambda_dir}')

    if using_chalice:
        logging.info(f'updating chalice configuration: {chalice_config_path}')
        with open(chalice_config_path) as f:
            chalice_config = json.load(f)
        chalice_env = chalice_config.setdefault('environment_variables', {})
        chalice_env['DEPLOYMENT_ENVIRONMENT'] = deployment_environment
        with open(chalice_config_path, 'w') as f:
            json.dump(chalice_config, f, indent=2)
        logging.info(f'updated chalice configuration: {chalice_config_path}')

        logging.info(f'templating policy: {policy_template_path}')
        with open(policy_template_path) as rf, open(policy_output_path, 'w') as wf:
            template = Template(rf.read())
            wf.write(template.substitute(os.environ))
        logging.info(f'templated policy: {policy_output_path}')

    logging.info(f'building lambda: {name}')
    if os.path.exists(join(lambda_dir, 'Dockerfile')):
        dockerfile_path = join(lambda_dir, 'Dockerfile')
    else:
        dockerfile_path = join('lambdas', 'Dockerfile')
    run([
        'docker', 'build',
        '-t', docker_tag,
        '-f', dockerfile_path,
        '--build-arg', f'DEPLOYMENT_ENVIRONMENT={deployment_environment}',
        '--build-arg', f'AWS_DEFAULT_REGION={os.environ["AWS_DEFAULT_REGION"]}',
        lambda_dir,
    ], check=True)
    cid = run(['docker', 'create', docker_tag], capture_output=True, check=True).stdout.decode().strip()
    os.makedirs(output_dir, exist_ok=True)
    # only check for errors when using chalice, otherwise chalice.tf.json will not be present
    run(['docker', 'cp', f'{cid}:/out/chalice.tf.json', output_dir], check=using_chalice, capture_output=True)
    run(['docker', 'cp', f'{cid}:/out/deployment.zip', output_dir], check=True, capture_output=True)
    run(['docker', 'rm', cid], check=True, capture_output=True)
    logging.info(f'built lambda to: {output_dir}')

    if using_chalice:
        logging.info(f'resetting chalice config: {chalice_config_path}')
        with open(chalice_config_path) as f:
            chalice_config = json.load(f)
        del chalice_config['environment_variables']['DEPLOYMENT_ENVIRONMENT']
        with open(chalice_config_path, 'w') as f:
            json.dump(chalice_config, f, indent=2)
        logging.info(f'reset chalice config: {chalice_config_path}')

        logging.info(f'modifying terraform json: {terraform_json_path}')
        with open(terraform_json_path) as f:
            terraform_json = json.load(f)
        del terraform_json['terraform']['required_version']
        if deployment_environment == 'test' and 'aws_lambda_permission' in terraform_json.get('resource'):
            # Disabled due to lack of support in moto
            del terraform_json['resource']['aws_lambda_permission']
        with open(terraform_json_path, 'w') as f:
            json.dump(terraform_json, f, indent=2)
        logging.info(f'modified terraform json: {terraform_json_path}')

    logging.info(f'packaging complete for: {name}')


if __name__ == '__main__':
    if len(sys.argv) > 1:
        package_lambda(sys.argv[1])
    else:
        lambdas = [name for name in os.listdir('lambdas') if os.path.isdir(join('lambdas', name))]
        with Pool() as pool:
            pool.map(package_lambda, lambdas)
