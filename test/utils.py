import os
import subprocess
import json


# Invokes miniwdl to run the pipeline step, and returns the response.
def run_pipeline_step(test_wdl, inputs={}):
    file_parameters = []
    for file_name, file_path in inputs.items():
        file_parameters.append(f"{file_name}={file_path}")

    try:
        res = subprocess.check_output(
            ["miniwdl", "run", test_wdl] + file_parameters + ["--error-json"]
        )
    except subprocess.CalledProcessError as e:
        # If there is an error, attempt to fetch and parse the error object.
        # We expect the last line of the stderr_file to be a JSON object describing the error.
        #
        # For other issues, like a wrong docker image tag, or a failure downloading an input file,
        # the cause will be something other than CommandFailed.
        try:
            value = json.loads(e.output.decode("utf8"))
            assert value["cause"]["error"] == "CommandFailed"
        except Exception:
            # If there was an unexpected error, re-raise the error.
            raise e

        stderr_file_path = value["cause"]["stderr_file"]
        error = json.loads(
            subprocess.check_output(["tail", "-1", stderr_file_path])
        )
        assert error["wdl_error_message"]
        return False, {
            "error": error["error"],
            "cause": error["cause"],
        }

    return True, json.loads(res)


# Returns the path to an empty file. Used for input files that a pipeline step doesn't actually use.
def get_placeholder_test_file_path():
    return os.path.join(
        os.environ["APP_HOME"], "test", "placeholder_test_file"
    )
