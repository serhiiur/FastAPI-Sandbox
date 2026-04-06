## About

Example of deploying a FasAPI application to AWS Lambda + AWS API Gateway.


## Prerequisites

Make sure [aws cli](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-getting-started.html) is installed on your machine and your AWS account has permissions to create AWS Lambda functions, IAM roles, and API Gateway.


## Deployment

The deployment process is automated and consists of the following steps:

  1. Install Python packages from [requirements.txt](requirements.txt) into <ins>packages/</ins> directory that will be bundled into a zip archive.

  2. Copy [api.py](api.py) file into <ins>package/</ins> directory and zip its content into <ins>deployment.zip</ins>.

  3. Create an IAM execution role to allow AWS Lambda to assume it. Also attach the *AWSLambdaBasicExecutionRole* policy for CloudWatch Logs access.

  4. Create the AWS Lambda function from <ins>deployment.zip</ins> archive on the first run. On subsequent runs, update the existing function code instead.

  5. Create an HTTP API Gateway to proxy all requests to the Lambda function.

  6. Grant API Gateway the *lambda:InvokeFunction* permission on the AWS Lambda function so that inbound HTTP requests can be forwarded to it.

  7. Remove <ins>package/</ins> directory and <ins>deployment.zip</ins> archive created during the build.

  8. Fetch the public API Gateway endpoint URL and print it to the console.


Use [deploy.sh](deploy.sh) script to deploy the FastAPI application to AWS Lambda + AWS API Gateway.

**Note**: make sure [deploy.sh](deploy.sh) script has executable permissions (`sudo chmod +x deploy.sh`).

The script usage pattern is:
```
./deploy.sh --aws-account-id <AWS-ACCOUNT-ID> [--aws-region <REGION>]
```

For example:
```bash
./deploy.sh --aws-account-id <AWS-ACCOUNT-ID> --aws-region us-east-1
```

**Note**: if you don't specify the `--aws-region` argument, the default value will be used (*us-east-1*).
