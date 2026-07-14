from botocore.exceptions import ClientError
import boto3
import re

def upload_to_s3(local_file_path, s3_bucket, s3_key):
    s3 = boto3.client('s3')
    s3.upload_file(local_file_path, s3_bucket, s3_key)
    print(f"📤 File uploaded to S3: s3://{s3_bucket}/{s3_key}")
    
def check_if_sorteo_exists(s3_bucket, year, sorteo_number):
    s3 = boto3.client('s3')
    key = f"processed/year={year}/sorteo={sorteo_number}/sorteos.parquet"
    try: 
        s3.head_object(Bucket=s3_bucket, Key=key)
        print(f"🔁 Sorteo {sorteo_number} ya existe en {key}")
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == "404":
            return False
        else:
            raise e
        
def list_files_in_s3(bucket_name, prefix):
    s3 = boto3.client('s3')
    paginator = s3.get_paginator('list_objects_v2') # using official paginator from s3
    page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
    all_keys = []
    for page in page_iterator:
        all_keys.extend([content['Key'] for content in page.get('Contents', []) if content['Key'].endswith(".txt")])
    return all_keys

def list_processed_sorteos_in_partitioned_bucket(bucket_name, prefix="processed/sorteos/"):
    s3 = boto3.client('s3')
    paginator = s3.get_paginator('list_objects_v2')
    operation_parameters = {'Bucket': bucket_name, 'Prefix': prefix}
    page_iterator = paginator.paginate(**operation_parameters)
    sorteos_procesados = set()
    for page in page_iterator:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            match = re.search(r"sorteo=(\d+)", key)
            if match:
                sorteos_procesados.add(int(match.group(1)))
    return sorteos_procesados

def download_file_from_s3(bucke_name, s3_key, local_path):
    """
    Downloads a file from S3 to the local filesystem.
    """
    s3 = boto3.client('s3')
    s3.download_file(bucke_name, s3_key, local_path)
    print(f"Downloaded {s3_key} to {local_path}")
    
def upload_file_to_s3(local_path, bucket_name, s3_key):
    """
    Uploads a file from the local filesystem to S3.
    """
    s3 = boto3.client('s3')
    s3.upload_file(local_path, bucket_name, s3_key)
    print(f"Uploaded {local_path} to s3://{bucket_name}/{s3_key}")