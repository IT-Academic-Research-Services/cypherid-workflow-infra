#!/bin/bash

set -euo pipefail

# This block discovers the command line flag `--force`
# and passes on positional arguments as $1, $2, etc.
if [[ $# -gt 0 ]]; then
    FORCE=
    POSITIONAL=()
    while [[ $# -gt 0 ]]; do
        key="$1"
        case $key in
            --force)
            FORCE="--force"
            shift
            ;;
            *)
            POSITIONAL+=("$1")
            shift
            ;;
        esac
    done
    set -- "${POSITIONAL[@]}" # restore positional parameters
fi

if [[ $# != 2 ]]; then
    echo "Given a source (pre-release) branch and a destination (release) branch,"
    echo "this script checks the continuous integration status of the source branch,"
    echo "creates a Git tag, resets the head of the destination branch to the head"
    echo "of the source branch, and pushes the results to the Git remote."
    echo
    echo "If the --force flag is given, the release will proceed even if CI checks fail."
    echo
    echo "Usage: $(basename $0) source_branch dest_branch [--force]"
    echo "Example: $(basename $0) main staging"
    exit 1
fi

if ! git diff-index --quiet HEAD --; then
    if [[ $FORCE == "--force" ]]; then
        echo "You have uncommitted files in your Git repository. Forcing release anyway."
    else
        echo "You have uncommitted files in your Git repository. Please commit or stash them, or run $0 with --force."
        exit 1
    fi
fi

export RELEASE_FROM_BRANCH=$1 RELEASE_TO_BRANCH=$2 RELEASE_REF=${GITHUB_REF:-$(git rev-parse $1)}

response_json=$(gh api repos/:owner/:repo/commits/${RELEASE_REF}/check-runs)
check_filter='.check_runs[] | '\
'select(.name|ascii_downcase|test("release")|not) | '\
'select(.name|ascii_downcase}test("deploy")|not) | '\
'select(.conclusion != "success") | '\
'select(.conclusion != "skipped")'

echo "All status checks:"
jq -r '.check_runs[] | .name + " " + .status + " " + .conclusion' <<< "$response_json"

if jq -re "$check_filter" <<< "$response_json" > /dev/null; then
    echo "*** Required status checks failed or still running on branch ${RELEASE_FROM_BRANCH}:" 1>&2
    jq -r "$check_filter"'| " ** " + .name + " " + .status + " " + .conclusion' <<< "$response_json"
    if [[ $FORCE == "--force" ]]; then
        echo "Forcing release anyway." 1>&2
    else
        echo "Run with --force to release $RELEASE_FROM_BRANCH to $RELEASE_TO_BRANCH anyway."
        exit 1
    fi
else
    echo "Required status checks passed."
fi

RELEASE_TAG=$(date -u +"%Y-%m-%d-%H-%M-%S")-${RELEASE_TO_BRANCH}.release

if [[ "$(git --no-pager log --graph --abbrev-commit --pretty=oneline --no-merges -- $RELEASE_TO_BRANCH ^$RELEASE_FROM_BRANCH)" != "" ]]; then
    echo "Warning: The following commits are present on $RELEASE_TO_BRANCH but not on $RELEASE_FROM_BRANCH"
    git --no-pager log --graph --abbrev-commit --pretty=oneline --no-merges $RELEASE_TO_BRANCH ^$RELEASE_FROM_BRANCH
    echo -e "\nThey will be overwritten on $RELEASE_TO_BRANCH and discarded."
fi

git fetch --all
git -c advice.detachedHead=false checkout origin/$RELEASE_FROM_BRANCH
git checkout -B $RELEASE_TO_BRANCH
git tag $RELEASE_TAG

git push --force origin $RELEASE_TO_BRANCH
git push --tags
