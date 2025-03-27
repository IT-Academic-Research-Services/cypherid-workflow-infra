# type: ignore

running_pipeline_runs = [
    {
        "pipeline_run_id": "pipeline_run_id_1",
        "background_id": "background_id_1",
        "deletion_task": "aaaa-1111-aaaa-1111:1111",
    }
]

running_tasks = [
    {
        "task": {
            "id": 1111,
            "node": "aaaa-1111-aaaa-1111",
        }
    }
]

succeeded_pipeline_runs = [
    {
        "pipeline_run_id": "pipeline_run_id_2",
        "background_id": "background_id_2",
        "deletion_task": "bbbb-2222-bbbb-2222:2222",
    }
]

succeeded_tasks = [
    {
        "completed": True,
        "task": {
            "id": 2222,
            "node": "bbbb-2222-bbbb-2222",
        },
        "response": {
            "failures": [],
        },
    }
]

failed_pipeline_runs = [
    {
        "pipeline_run_id": "pipeline_run_id_4",
        "background_id": "background_id_4",
        "deletion_task": "dddd-4444-dddd-4444:4444",
    }
]

failed_tasks = [
    {
        "completed": True,
        "task": {
            "id": 4444,
            "node": "dddd-4444-dddd-4444",
        },
        "response": {
            "failures": [{"status": 404}],
        },
    }
]

missing_pipeline_runs = [
    {
        "pipeline_run_id": "pipeline_run_id_3",
        "background_id": "background_id_3",
        "deletion_task": "cccc-3333-cccc-3333:3333",
    }
]

missing_tasks = [{"id": "3333", "node": "cccc-3333-cccc-3333"}]

task_statuses = {
    "missing_tasks": {"tasks": missing_tasks, "pipeline_runs": missing_pipeline_runs},
    "running_tasks": {"tasks": running_tasks, "pipeline_runs": running_pipeline_runs},
    "succeeded_tasks": {
        "tasks": succeeded_tasks,
        "pipeline_runs": succeeded_pipeline_runs,
    },
    "failed_tasks": {"tasks": failed_tasks, "pipeline_runs": failed_pipeline_runs},
}
