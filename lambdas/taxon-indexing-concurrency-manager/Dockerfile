# Build-only image: the container is `docker create`d and /out/deployment.zip is
# `docker cp`'d out (see scripts/package_lambda.py); it is never `docker run`.
# A non-root USER is still applied for image hygiene (CKV_DOCKER_3 / DS-0002).
FROM node:20

# apt cleanup keeps the layer small and clears DS-0029 (no-install-recommends + list cleanup).
RUN apt-get update \
    && apt-get install -y --no-install-recommends zip \
    && rm -rf /var/lib/apt/lists/*

# Create an unprivileged build user owning the working + output dirs.
RUN useradd --create-home --uid 10001 lambdabuild \
    && mkdir -p /app /out \
    && chown -R lambdabuild:lambdabuild /app /out

WORKDIR /app
USER lambdabuild

COPY --chown=lambdabuild:lambdabuild package.json package-lock.json /app/

RUN npm install

COPY --chown=lambdabuild:lambdabuild app.js app.js

RUN zip -r /out/deployment.zip .
