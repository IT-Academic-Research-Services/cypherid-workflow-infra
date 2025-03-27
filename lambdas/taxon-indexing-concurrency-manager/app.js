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

async function invoke_taxon_indexing(pipeline_run_ids, background_id, concurrency, es_batchsize) {
    const limit = pLimit(concurrency);

    const result = await Promise.all(
        pipeline_run_ids.map(
            pipeline_run_id => pRetry(
                () => limit(
                    async () => invoke_lambda({
                        pipeline_run_id,
                        background_id,
                        es_batchsize,
                        concurrency
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
    result.map(x => x.Payload = new TextDecoder().decode(x.Payload))
    const errorResults = result.filter((x => x.FunctionError))
    const successResults = result.filter((x => !x.FunctionError))
    if (errorResults.length > 0) {
        console.error(errorResults)
        throw new Error(`${errorResults.length} / ${successResults.length} pipeline runs failed to index. See logs for more details.`)
    }
    return result
    
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

    return invoke_taxon_indexing(pipeline_run_ids, background_id, concurrency, es_batchsize)
  }
