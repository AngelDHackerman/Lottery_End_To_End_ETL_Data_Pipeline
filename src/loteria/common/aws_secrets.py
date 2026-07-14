from botocore.exceptions import ClientError
import boto3
import json


# Get the secret from AWS Secrets Manager
def get_secrets():
    secret_name = "lottery_secret_prod_2"
    region_name = "us-east-1"
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager', region_name=region_name)
    try:
        response = client.get_secret_value(SecretId=secret_name)
        secret = json.loads(response['SecretString'])
        return {
            "simple": secret["s3_bucket_simple_data_storage_prod_arn"].split(":::")[-1],
            "partitioned": secret["s3_bucket_partitioned_data_storage_prod_arn"].split(":::")[-1],
            "scrape_do_token": secret["scrape_do_token"].split(":::")[-1]
        }
    except ClientError as e:
        raise e
