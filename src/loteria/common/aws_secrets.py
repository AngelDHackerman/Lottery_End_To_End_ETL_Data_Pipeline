import json
import os
import re

import boto3
from botocore.exceptions import ClientError

# Cloning into a new account should only require changing the secret name in ONE place:
# the LOTERIA_SECRET_NAME env var (set by Terraform — see terraform/modules/etl-lambda
# and etl-glue). The defaults keep the current prod behaviour when the vars are unset.
# PR-034: the B105 suppression below. This is the secret's NAME in Secrets Manager, not its
# value — bandit's hardcoded-password heuristic fires on any assignment to an identifier
# containing "secret". The name is deliberately public: it is what the IAM policies scope to,
# and it appears in terraform/ and in the runbooks.
DEFAULT_SECRET_NAME = "lottery_secret_prod_2"  # nosec B105
DEFAULT_REGION = "us-east-1"

# Matches an S3 bucket ARN like "arn:aws:s3:::my-bucket-name" (also aws-us-gov / aws-cn).
_S3_ARN_RE = re.compile(r"^arn:aws[a-z-]*:s3:::(?P<bucket>[^/]+)$")


def _bucket_name(value: str) -> str:
    """Return the bucket name from an S3 ARN, or ``value`` unchanged if it is already a
    bare bucket name.

    Replaces the old brittle ``.split(":::")[-1]`` slice, which silently mangled any
    value that happened to contain ``:::``.

    FOLLOW-UP: the secret payload should store bucket *names* directly, not ARNs. Once
    it does, this ARN-stripping shim can be deleted and the values used verbatim.
    """
    match = _S3_ARN_RE.match(value)
    return match.group("bucket") if match else value


# Get the secret from AWS Secrets Manager
def get_secrets():
    secret_name = os.environ.get("LOTERIA_SECRET_NAME", DEFAULT_SECRET_NAME)
    region_name = os.environ.get("AWS_REGION", DEFAULT_REGION)
    session = boto3.session.Session()
    client = session.client(service_name="secretsmanager", region_name=region_name)
    try:
        response = client.get_secret_value(SecretId=secret_name)
        secret = json.loads(response["SecretString"])
        # PR-041.2: `s3_bucket_simple_data_storage_prod_arn` is still IN the secret payload
        # and is deliberately not read. Terraform does not own the payload — removing the
        # key there is a manual owner edit, filed as a follow-up in
        # docs/runbooks/PR-041-retire-simple-bucket.md. Dropping it here first is the half
        # that can be code-reviewed, and it is what makes `get_secrets()` stop handing every
        # caller a bucket name nothing may write to any more.
        return {
            "partitioned": _bucket_name(secret["s3_bucket_partitioned_data_storage_prod_arn"]),
            "scrape_do_token": secret["scrape_do_token"],
        }
    except ClientError as e:
        raise e
