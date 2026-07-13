# Default Dockerfile for lambdas, packages with chalice
#   scripts/package_lambda.py will use this to build images if it doesn't find a dockerfile
# This is a build-only image: the container is `docker create`d and the packaged
# artifacts are `docker cp`'d out of /out (see scripts/package_lambda.py); it is
# never `docker run`. A non-root USER is still applied for image hygiene (CKV_DOCKER_3 / DS-0002).
FROM python:3.12

# Create an unprivileged build user and the writable dirs the packaging step needs.
RUN useradd --create-home --uid 10001 lambdabuild \
    && mkdir -p /app /out \
    && chown -R lambdabuild:lambdabuild /app /out

COPY --chown=lambdabuild:lambdabuild requirements.txt .

USER lambdabuild

# Install into the user site so no root-owned paths are required at build time.
ENV PATH="/home/lambdabuild/.local/bin:${PATH}"
RUN pip install --no-cache-dir --user -r requirements.txt

WORKDIR /app
COPY --chown=lambdabuild:lambdabuild . .

ARG DEPLOYMENT_ENVIRONMENT
ARG AWS_DEFAULT_REGION

RUN chalice package --pkg-format terraform --stage $DEPLOYMENT_ENVIRONMENT /out
