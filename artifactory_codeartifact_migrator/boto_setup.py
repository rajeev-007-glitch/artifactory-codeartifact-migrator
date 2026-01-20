import boto3
import os

# Only set up a specific profile if one is explicitly provided
# Otherwise boto3 will automatically use IAM role credentials (for EC2) or environment variables
if os.environ.get('AWS_PROFILE'):
    boto3.setup_default_session(profile_name=os.environ.get('AWS_PROFILE'))
else:
    # Let boto3 use IAM role credentials or environment variables automatically
    pass