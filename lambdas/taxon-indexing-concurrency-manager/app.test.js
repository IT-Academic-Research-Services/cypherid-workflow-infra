import { test } from 'node:test'
import assert from 'node:assert/strict'
import { classifyResults, failureMessage } from './app.js'

// A worker Lambda that threw: 200 response with FunctionError set.
const functionError = () => ({ StatusCode: 200, FunctionError: 'Unhandled', Payload: new TextEncoder().encode('{"errorMessage":"boom"}') })
// A successful worker invocation.
const success = () => ({ StatusCode: 200, Payload: new TextEncoder().encode('{"success":true}') })
// A hard invocation failure caught by `.catch(err => err)`: a plain Error.
const hardError = () => new Error('ThrottlingException: rate exceeded')

test('failureMessage reports failed / TOTAL, not failed / succeeded', () => {
    // Regression for the "11 / 0" wording: a fully-failed batch of 11 must read 11 / 11.
    assert.equal(failureMessage(11, 11), '11 / 11 pipeline runs failed to index. See logs for more details.')
    assert.equal(failureMessage(1, 1), '1 / 1 pipeline runs failed to index. See logs for more details.')
    assert.equal(failureMessage(3, 5), '3 / 5 pipeline runs failed to index. See logs for more details.')
})

test('classifyResults counts FunctionError responses as failures', () => {
    const { errorResults, successResults } = classifyResults([functionError(), functionError()])
    assert.equal(errorResults.length, 2)
    assert.equal(successResults.length, 0)
})

test('classifyResults counts a hard Error (no FunctionError) as a failure, not a success', () => {
    // The previous filter(x => !x.FunctionError) miscounted these as successes.
    const { errorResults, successResults } = classifyResults([hardError(), success()])
    assert.equal(errorResults.length, 1)
    assert.equal(successResults.length, 1)
})

test('classifyResults splits a mixed batch correctly', () => {
    const { errorResults, successResults } = classifyResults([success(), functionError(), hardError(), success()])
    assert.equal(errorResults.length, 2)
    assert.equal(successResults.length, 2)
})

test('classifyResults decodes Payload only on real responses, never on Error objects', () => {
    const results = [success(), hardError()]
    classifyResults(results)
    assert.equal(typeof results[0].Payload, 'string')       // decoded
    assert.ok(results[1] instanceof Error)                  // untouched, no crash
})
