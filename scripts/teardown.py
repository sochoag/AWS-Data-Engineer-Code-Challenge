"""
teardown.py
Safely removes all AWS resources created by the challenge.

Steps:
  1. Empty the S3 bucket (CloudFormation cannot delete a non-empty bucket)
  2. Run `sam delete` to remove the entire CloudFormation stack

Usage:
    python scripts/teardown.py
"""

import boto3
import subprocess
import sys

PROFILE    = "sam-deployer"
STACK_NAME = "cc-data-engineer-etl"
REGION     = "us-east-1"


def get_bucket_name(cf_client: boto3.client) -> str:
    response = cf_client.describe_stacks(StackName=STACK_NAME)
    outputs  = response["Stacks"][0].get("Outputs", [])
    for output in outputs:
        if output["OutputKey"] == "DataBucketName":
            return output["OutputValue"]
    raise ValueError(
        f"'DataBucketName' not found in stack '{STACK_NAME}'. "
        "Does the stack exist?"
    )


def empty_bucket(s3_resource, bucket_name: str) -> None:
    """Deletes all objects and versions from the bucket."""
    bucket  = s3_resource.Bucket(bucket_name)
    deleted = 0

    print(f"  Deleting objects from s3://{bucket_name} ...")

    # Regular objects
    objects = list(bucket.objects.all())
    if objects:
        bucket.delete_objects(
            Delete={"Objects": [{"Key": obj.key} for obj in objects]}
        )
        deleted += len(objects)

    # Versioned objects (bucket has versioning enabled)
    versions = list(bucket.object_versions.all())
    if versions:
        bucket.delete_objects(
            Delete={
                "Objects": [
                    {"Key": v.object_key, "VersionId": v.id} for v in versions
                ]
            }
        )
        deleted += len(versions)

    print(f"  Deleted {deleted} objects/versions.")


def delete_stack() -> None:
    """Runs sam delete to remove the CloudFormation stack."""
    print(f"\nDeleting stack '{STACK_NAME}' with sam delete ...")
    result = subprocess.run(
        [
            "sam", "delete",
            "--stack-name", STACK_NAME,
            "--region", REGION,
            "--profile", PROFILE,
            "--no-prompts",
        ],
        capture_output=False,
    )
    if result.returncode != 0:
        print("ERROR: sam delete failed. Check the logs above.")
        sys.exit(1)


def main() -> None:
    print("=" * 55)
    print("  TEARDOWN — Data Engineer Challenge")
    print("=" * 55)

    confirm = input(
        "\n⚠️  This will permanently delete ALL AWS resources created by this challenge.\n"
        "Are you sure? (y/n): "
    ).strip().lower()

    if confirm != "y":
        print("Teardown cancelled.")
        sys.exit(0)

    session     = boto3.Session(profile_name=PROFILE)
    cf_client   = session.client("cloudformation", region_name=REGION)
    s3_resource = session.resource("s3", region_name=REGION)

    # 1. Get bucket name
    print(f"\nRetrieving resources from stack '{STACK_NAME}'...")
    try:
        bucket = get_bucket_name(cf_client)
        print(f"  Bucket: {bucket}")
    except Exception as e:
        print(f"  Could not retrieve bucket ({e}). Proceeding with sam delete...")
        bucket = None

    # 2. Empty the bucket
    if bucket:
        empty_bucket(s3_resource, bucket)

    # 3. Delete the stack
    delete_stack()

    print("\n✅ Teardown complete. All AWS resources have been deleted.")


if __name__ == "__main__":
    main()
