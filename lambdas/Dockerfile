# Default Dockerfile for lambdas, packages with chalice
#   scripts/package_lambda.py will use this to build images if it doesn't find a dockerfile
FROM python:3.8

COPY requirements.txt .
RUN pip install -r requirements.txt

WORKDIR /app
COPY . .

ARG DEPLOYMENT_ENVIRONMENT
ARG AWS_DEFAULT_REGION

RUN chalice package --pkg-format terraform --stage $DEPLOYMENT_ENVIRONMENT /out
