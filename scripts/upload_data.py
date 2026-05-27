"""
upload_data.py
Uploads the source CSVs and Glue scripts to the S3 bucket.
Run AFTER `sam deploy`, once the bucket has been created.

Usage:
    python scripts/upload_data.py
"""

import boto3
import sys
from pathlib import Path

PROFILE    = "sam-deployer"
STACK_NAME = "cc-data-engineer-etl"

# Files to upload: (local path relative to project root, S3 key)
UPLOADS = [
    ("data/battery14_df.csv",   "raw/battery14_df.csv"),
    ("data/degrees.csv",        "raw/degrees.csv"),
    ("glue/glue_transform.py",  "scripts/glue_transform.py"),
    ("glue/glue_iceberg.py",    "scripts/glue_iceberg.py"),
]


def get_bucket_name(cf_client: boto3.client) -> str:
    """Retrieves the bucket name from the CloudFormation stack outputs."""
    response = cf_client.describe_stacks(StackName=STACK_NAME)
    outputs  = response["Stacks"][0].get("Outputs", [])
    for output in outputs:
        if output["OutputKey"] == "DataBucketName":
            return output["OutputValue"]
    raise ValueError(
        f"'DataBucketName' not found in stack '{STACK_NAME}' outputs. "
        "Did you run `sam deploy` first?"
    )


def upload_files(s3_client: boto3.client, bucket: str, project_root: Path) -> None:
    """Uploads each file to its corresponding S3 prefix."""
    for local_path, s3_key in UPLOADS:
        full_path = project_root / local_path
        if not full_path.exists():
            print(f"  ⚠️  File not found, skipping: {full_path}")
            continue
        print(f"  Uploading {local_path} → s3://{bucket}/{s3_key}")
        s3_client.upload_file(str(full_path), bucket, s3_key)

    print()


def list_bucket(s3_client: boto3.client, bucket: str) -> None:
    """Lists bucket contents to verify the upload."""
    paginator = s3_client.get_paginator("list_objects_v2")
    print(f"Contents of s3://{bucket}/")
    print("-" * 60)
    total_size = 0
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            size_kb = obj["Size"] / 1024
            print(f"  {obj['Key']:<55} {size_kb:>8.1f} KB")
            total_size += obj["Size"]
    print("-" * 60)
    print(f"  Total: {total_size / 1024:.1f} KB\n")


def main() -> None:
    # Project root is the parent directory of this script
    project_root = Path(__file__).parent.parent

    session   = boto3.Session(profile_name=PROFILE)
    cf_client = session.client("cloudformation", region_name="us-east-1")
    s3_client = session.client("s3", region_name="us-east-1")

    print(f"Retrieving bucket name from stack '{STACK_NAME}'...")
    try:
        bucket = get_bucket_name(cf_client)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"Bucket: {bucket}\n")
    print("Uploading files...")
    upload_files(s3_client, bucket, project_root)

    print("✅ Upload complete.\n")
    list_bucket(s3_client, bucket)


if __name__ == "__main__":
    main()
