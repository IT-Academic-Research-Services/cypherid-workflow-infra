# lambdas

This directory contains the source code and dependencies for our lambdas. The motivation for this structure is to allow us to reproducibly deploy our lambdas with the correct versions of their dependencies. The script `scripts/package_lambda.py` packages these lambdas as zip files and terraform and places them in `terraform/modules`. Each directory represents a lambda (or several related lambdas) and corresponds to a directory in `terraform/modules` where it's package will go for deployment. By default the build supports lambdas using [chalice](https://github.com/aws/chalice) though you can write any type of lambda that expects a zip file.

## Creating a Lambda

To create a new lambda, create a new top-level directory in this directory. Ensure the name of your directory doesn't conflict with the names of the directories in `terraform/modules`. With [chalice](https://github.com/aws/chalice) you can also create several lambdas in one directory. This is a good option if they require common code between them or are related in some way.

The build script here will place your packaged lambda in the modules directory as a module. To actually create your lambda you will need to create the module in `terraform/idseq.tf`:

```HCL
module "your-lambda-name" {
  source = "./modules/your-lambda-name"
}
```

### With Chalice

If you are using chalice you need the following files:

- `.chalice/config.json`: your chalice configuration
- Main python file (i.e. `app.py`): the main file for your lambda, where you will set up your chalice application
- `policy-template.json`: a template for your lambda's IAM policy. Template variables are denoted with `$`. You can template values like: `AWS_ACCOUNT_ID`, `AWS_DEFAULT_REGION`, and `DEPLOYMENT_ENVIRONMENT` make your policy work in different environments
- `requirements.txt`: your PyPI requirements, using the constraint `~=` to constrain them to the minor version. chalice must be in here. The reason you need to install chalice yourself in each requirements file is so you can develop in a virtual environment per lambda and reference the correct version of chalice locally

You can also add other python files if you want to structure your code that way.

### Without Chalice

If you are making a lambda without chalice the requirements a slightly different. This setup will not create the full lambda for you, it will just package your source code. You will need to manually create your lambda with terraform. See `Adding Terraform to your Lambda` > `Configuring a Lambda Without Chalice` for more information. All you need from your lambda source directory is a `Dockerfile` that produces your lambda's zip and stores it internally as `/out/deployment.zip`. It should install all required dependencies, you can do this using your language's package manager like `npm` for node. Note the version of the language you use in your Dockerfile, it should match up with the version you set when you create the lambda manually in terraform.

An example `Dockerfile`:

```dockerfile
FROM node:16

RUN apt-get update && apt-get install -y zip

COPY package.json package-lock.json /app/

WORKDIR /app

RUN npm install

COPY app.js app.js

RUN mkdir /out

RUN zip -r /out/deployment.zip .
```

## Adding Terraform to Your Lambda

If you want to develop terraform that depends on your lambdas you can create a module directory with the same name as your lambda directory in `terraform/modules` and add your terraform code.

### Building on your Lambda with Chalice

When using chalice you define some information, like the name and handler of your lambda, in code like so:

```python
from chalice import Chalice


app = Chalice(app_name="your-lambda-name")

@app.lambda_function()
def your_handler():
    pass
```

Chalice will run this code and use it to generate the equivilent terraform which will be placed into the module. You will be able to reference your lambda, and associated resources as normal terraform resources within the module. In the above example chalice would call the lambda terraform resource `your_handler` so you could access it within the module like so:

```HCL
output "lambda_arn" {
    value = aws_lambda_function.your_handler.arn
}
```

If you want to be confident about what resources will be called run `make package-lambdas`. This will generate the terraform code and place it in `terraform/modules/your-lambda-name/chalice.tf.json`. The format is json instead of HCL but it is referencable terraform with resource names.

This example also demonstrates how you can build on top of your lambda. By outputting the arn from the terraform module, you can pass it into your other terraform configuration and build resources referencing your lambda.

### Configuring a Lambda Without Chalice (mandatory if not using chalice)

Without chalice you need to add some terraform code. Your lambda source code will be stored in `deployment.zip` so you need to actually create your lambda. Here is a minimal example:

```HCL
resource "aws_iam_role" "role" {
  name = "your-lambda-name-${var.deployment_environment}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Sid    = ""
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "policy" {
  name = "your-lambda-name-${var.deployment_environment}-rolePolicy"
  role = aws_iam_role.role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData",
          "iam:ListAccountAliases"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:CreateNetworkInterface",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DetachNetworkInterface",
          "ec2:DeleteNetworkInterface"
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_lambda_function" "taxon_indexing_concurrency_manager" {
  function_name    = "your-lambda-name-${var.deployment_environment}"
  runtime          = "nodejs16.x"
  # This should reference a function in your source code
  handler          = "app.handler"
  memory_size      = 512
  timeout          = 900
  # Here is where we reference the `deployment.zip` output
  source_code_hash = filebase64sha256("${path.module}/deployment.zip")
  filename         = "${path.module}/deployment.zip"
  role             = aws_iam_role.role.arn
}
```
