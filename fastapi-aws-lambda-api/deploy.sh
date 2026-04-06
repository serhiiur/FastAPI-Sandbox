#!/bin/bash

set -e

FUNCTION_NAME="fastapi-app"
ROLE_NAME="fastapi-lambda-role"
API_NAME="fastapi-app"
HANDLER="api.handler"
RUNTIME="python3.12"
TIMEOUT=30
MEMORY=256

# Parse input script arguments:
#   --aws-account-id
#   --aws-region (defaults to us-east-1)
parse_args() {
  AWS_ACCOUNT_ID=""
  AWS_REGION="us-east-1"

  while [[ $# -gt 0 ]]; do
    case $1 in
      --aws-account-id) AWS_ACCOUNT_ID=$2 shift 2 ;;
      --aws-region) AWS_REGION=$2 shift 2 ;;
      *)
        echo "Unknown argument: $1"
        echo "Usage: $0 --aws-account-id <ID> --aws-region <REGION>"
        exit 1
        ;;
    esac
  done

  if [ -z "$AWS_ACCOUNT_ID" ]; then
    echo "Usage: $0 --aws-account-id <ID> [--aws-region <REGION>]"
    exit 1
  fi
}

# Install Python packages from requirements.txt into packages/ directory
# that will be bundled into a zip archive.
install_dependencies() {
  echo "==> [1/7] Installing dependencies into package/"
  pip install -r requirements.txt -t package/ --quiet
}

# Copy api.py file into the package/ directory and zip its content into
# the archive called deployment.zip.
build_zip() {
  echo "==> [2/7] Building deployment.zip"
  cp api.py package/
  cd package
  zip -r ../deployment.zip . --quiet
  cd ..
}

# Create an IAM execution role to allow AWS Lambda to assume it.
# Also attach the AWSLambdaBasicExecutionRole policy for CloudWatch Logs access.
create_iam_role() {
  echo "==> [3/7] Creating IAM execution role: $ROLE_NAME"

  if aws iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
    echo "     Role already exists, skipping."
    return
  fi

  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole"
      }]
    }' > /dev/null

  aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

  echo "     Waiting for role to propagate..."
  sleep 10
}

# Create the AWS Lambda function from the archive deployment.zip on the first run.
# On subsequent runs, update the existing function code instead.
deploy_lambda() {
  echo "==> [4/7] Deploying Lambda function: $FUNCTION_NAME"

  local role_arn="arn:aws:iam::${AWS_ACCOUNT_ID}:role/${ROLE_NAME}"

  if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$AWS_REGION" &>/dev/null; then
    echo "     Function exists, updating code..."
    aws lambda update-function-code \
      --function-name "$FUNCTION_NAME" \
      --zip-file fileb://deployment.zip \
      --region "$AWS_REGION" > /dev/null
  else
    aws lambda create-function \
      --function-name "$FUNCTION_NAME" \
      --runtime "$RUNTIME" \
      --role "$role_arn" \
      --handler "$HANDLER" \
      --zip-file fileb://deployment.zip \
      --timeout "$TIMEOUT" \
      --memory-size "$MEMORY" \
      --region "$AWS_REGION" > /dev/null
  fi
}

# Create an HTTP API Gateway to proxy all requests to the Lambda function.
# Store the resulting API ID in $API_ID for use by subsequent steps.
setup_api_gateway() {
  echo "==> [5/7] Setting up API Gateway HTTP API: $API_NAME"

  local lambda_arn="arn:aws:lambda:${AWS_REGION}:${AWS_ACCOUNT_ID}:function:${FUNCTION_NAME}"

  local existing_api_id
  existing_api_id=$(aws apigatewayv2 get-apis \
    --region "$AWS_REGION" \
    --query "Items[?Name=='${API_NAME}'].ApiId" \
    --output text)

  if [ -n "$existing_api_id" ] && [ "$existing_api_id" != "None" ]; then
    echo "     API Gateway already exists (ID: $existing_api_id), skipping."
    API_ID=$existing_api_id
    return
  fi

  local api_output
  api_output=$(aws apigatewayv2 create-api \
    --name "$API_NAME" \
    --protocol-type HTTP \
    --target "$lambda_arn" \
    --region "$AWS_REGION")

  API_ID=$(echo "$api_output" | python3 -c "import sys,json; print(json.load(sys.stdin)['ApiId'])")
}

# Grant API Gateway the lambda:InvokeFunction permission on the AWS Lambda function
# so that inbound HTTP requests can be forwarded to it.
grant_api_gateway_permission() {
  echo "==> [6/7] Granting API Gateway permission to invoke Lambda"
  aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id "api-gateway-invoke" \
    --action lambda:InvokeFunction \
    --principal apigateway.amazonaws.com \
    --region "$AWS_REGION" &>/dev/null || echo "     Permission already exists, skipping."
}

# Remove package/ directory and deployment.zip archive created during the build.
cleanup() {
  echo "==> [7/7] Cleaning up build artifacts"
  rm -rf package/ deployment.zip
}

# Fetch the public API Gateway endpoint URL and print it to the console.
print_result() {
  local api_endpoint
  api_endpoint=$(aws apigatewayv2 get-api \
    --api-id "$API_ID" \
    --region "$AWS_REGION" \
    --query 'ApiEndpoint' \
    --output text)

  echo ""
  echo "Deployment complete!"
  echo "API Endpoint: ${api_endpoint}"
}

# Main function to completely deploy FastAPI application to AWS Lambda + API Gateway
main() {
  parse_args "$@"
  install_dependencies
  build_zip
  create_iam_role
  deploy_lambda
  setup_api_gateway
  grant_api_gateway_permission
  cleanup
  print_result
}

main "$@"
