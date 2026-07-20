import axios from 'axios';
import pLimit from 'p-limit';
import pRetry, {AbortError} from 'p-retry';
import { LambdaClient, InvokeCommand, TooManyRequestsException } from "@aws-sdk/client-lambda";

const lambda = new LambdaClient({
    apiVersion: '2015-03-31',
    maxAttempts: 0 // disable the automatic client retries because we are handling retries
});
let { 
    INDEX_TAXONS_FUNCTION_NAME,
    LOCAL_MODE,
    LOCAL_LAMBDA_ENDPOINT,
    CONCURRENCY
} = process.env
CONCURRENCY = parseInt(CONCURRENCY) || 50
const DEFAULT_ES_BATCHSIZE = 1000

async function invoke_taxon_indexing(pipeline_run_ids, background_id, concurrency, es_batchsize, es_host) {
    const limit = pLimit(concurrency);

    const result = await Promise.all(
        pipeline_run_ids.map(
            pipeline_run_id => pRetry(
                () => limit(
                    async () => invoke_lambda({
                        pipeline_run_id,
                        background_id,
                        es_batchsize,
                        concurrency,
                        // Forward the caller's target OpenSearch host to each worker so a preview
                        // sandbox's indexing lands in its isolated sandbox domain. Undefined for
                        // dev/staging/prod -> JSON.stringify drops it -> worker uses its own host.
                        es_host
                    }).catch(
                        (error) => {
                            if (!(error instanceof TooManyRequestsException)) {
                                // rethrow the error to trigger a retry
                                throw error
                            } else {
                                // throw an abort error to cancel retries
                                throw new AbortError(error);
                            }
                        }
                    )
                ),
                {
	                retries: 3
                },
            ).catch(err => err) // catch errors so that we can return the results of all requests in the final response
        ), 
    )
    const { errorResults } = classifyResults(result)
    if (errorResults.length > 0) {
        console.error(errorResults)
        throw new Error(failureMessage(errorResults.length, result.length))
    }
    return result

}

// Split the Promise.all results into failures vs successes. Two failure shapes:
// (1) a worker Lambda that threw returns a 200 InvokeCommand response with
// FunctionError set; (2) an invocation that hard-failed after retries (network /
// throttle) was caught above by `.catch(err => err)` and is a plain Error with no
// FunctionError. BOTH are failures -- the previous `filter(x => !x.FunctionError)`
// miscounted the hard failures as successes. Payload only exists on real
// InvokeCommand responses, so only decode those. Exported for unit tests.
// See platform-overhaul 724.
export function classifyResults(results) {
    results.forEach(x => {
        if (!(x instanceof Error) && x.Payload) {
            x.Payload = new TextDecoder().decode(x.Payload)
        }
    })
    const errorResults = results.filter(x => x instanceof Error || x.FunctionError)
    const successResults = results.filter(x => !(x instanceof Error) && !x.FunctionError)
    return { errorResults, successResults }
}

// failed / TOTAL. The old message used failed/succeeded, so a fully-failed batch
// printed "11 / 0" -- which reads as "11 of 0" instead of "11 of 11".
export function failureMessage(failedCount, total) {
    return `${failedCount} / ${total} pipeline runs failed to index. See logs for more details.`
}

async function invoke_lambda(payload) {
    if (LOCAL_MODE == "local") {
        const response = await axios.post(`http://${LOCAL_LAMBDA_ENDPOINT}/2015-03-31/functions/function/invocations`, payload)
        return response.data
    } else {
        return lambda.send(
            new InvokeCommand({
                FunctionName: INDEX_TAXONS_FUNCTION_NAME,
                InvocationType: 'RequestResponse',
                Payload: JSON.stringify(payload)
            })
        )
    }
}

export const handler = async (event, context) => {
    const pipeline_run_ids = event.pipeline_run_ids
    const background_id = event.background_id
    const concurrency = event.concurrency || CONCURRENCY
    const es_batchsize = event.es_batchsize || DEFAULT_ES_BATCHSIZE
    const es_host = event.es_host

    return invoke_taxon_indexing(pipeline_run_ids, background_id, concurrency, es_batchsize, es_host)
  }
