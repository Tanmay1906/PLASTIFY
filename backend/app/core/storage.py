"""PLASTIFY Secure Object Storage Abstraction.

Supports Amazon S3 and MinIO (S3-compatible object storage) with short-lived presigned URLs,
as well as a memory-backed mock storage service for hermetic testing.
"""

from abc import ABC, abstractmethod
import io
import logging
import time
from typing import Optional
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import Settings

logger = logging.getLogger("plastify.storage")


class IStorageService(ABC):
    """Abstract interface defining required object storage capabilities."""

    @abstractmethod
    def upload_file(
        self, file_content: bytes, storage_key: str, content_type: str
    ) -> str:
        """Upload raw file bytes into object storage under specified key."""
        pass

    @abstractmethod
    def generate_presigned_url(
        self, storage_key: str, expires_in: int = 900
    ) -> str:
        """Generate short-lived signed URL for secure file retrieval."""
        pass

    @abstractmethod
    def delete_file(self, storage_key: str) -> bool:
        """Delete an object from storage."""
        pass

    @abstractmethod
    def file_exists(self, storage_key: str) -> bool:
        """Verify whether an object exists at the given storage key."""
        pass


class S3StorageService(IStorageService):
    """Production S3 and local MinIO object storage client using boto3."""

    def __init__(self, settings: Settings) -> None:
        self.bucket_name = settings.S3_BUCKET_NAME
        self.default_expiry = settings.S3_SIGNED_URL_EXPIRE_SECONDS

        boto_config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},  # Path-style works seamlessly with MinIO
            retries={"max_attempts": 3, "mode": "standard"},
        )

        client_kwargs = {
            "service_name": "s3",
            "region_name": settings.S3_REGION_NAME,
            "aws_access_key_id": settings.S3_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.S3_SECRET_ACCESS_KEY,
            "use_ssl": settings.S3_USE_SSL,
            "config": boto_config,
        }

        if settings.S3_ENDPOINT_URL:
            client_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL

        self.s3_client = boto3.client(**client_kwargs)
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self) -> None:
        """Ensure the target bucket exists, creating it automatically in dev/MinIO environments."""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code in ["404", "NoSuchBucket"]:
                logger.info(f"Bucket '{self.bucket_name}' not found. Creating bucket...")
                try:
                    self.s3_client.create_bucket(Bucket=self.bucket_name)
                    logger.info(f"Bucket '{self.bucket_name}' created successfully.")
                except Exception as create_err:
                    logger.warning(f"Could not auto-create bucket: {create_err}")
            else:
                logger.warning(f"Could not verify bucket '{self.bucket_name}': {e}")

    def upload_file(
        self, file_content: bytes, storage_key: str, content_type: str
    ) -> str:
        """Upload byte buffer directly to S3/MinIO bucket."""
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=storage_key,
                Body=file_content,
                ContentType=content_type,
            )
            return storage_key
        except ClientError as e:
            logger.error(f"S3 upload error for key '{storage_key}': {e}")
            raise RuntimeError(f"Storage upload failed: {e}") from e

    def generate_presigned_url(
        self, storage_key: str, expires_in: Optional[int] = None
    ) -> str:
        """Generate short-lived signed GET URL for downloading."""
        ttl = expires_in or self.default_expiry
        try:
            url = self.s3_client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": self.bucket_name, "Key": storage_key},
                ExpiresIn=ttl,
            )
            return url
        except ClientError as e:
            logger.error(f"Error generating presigned URL for '{storage_key}': {e}")
            raise RuntimeError(f"Presigned URL generation failed: {e}") from e

    def delete_file(self, storage_key: str) -> bool:
        """Delete object from S3."""
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=storage_key)
            return True
        except ClientError as e:
            logger.error(f"S3 delete error for '{storage_key}': {e}")
            return False

    def file_exists(self, storage_key: str) -> bool:
        """Check if object exists in S3."""
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=storage_key)
            return True
        except ClientError:
            return False


class MockStorageService(IStorageService):
    """In-memory mock storage client for hermetic, network-isolated testing."""

    def __init__(self, bucket_name: str = "plastify-evidence-test") -> None:
        self.bucket_name = bucket_name
        self.objects: dict[str, tuple[bytes, str]] = {}

    def upload_file(
        self, file_content: bytes, storage_key: str, content_type: str
    ) -> str:
        self.objects[storage_key] = (file_content, content_type)
        return storage_key

    def generate_presigned_url(
        self, storage_key: str, expires_in: int = 900
    ) -> str:
        expires_timestamp = int(time.time()) + expires_in
        return (
            f"https://storage.plastify.test/{self.bucket_name}/{storage_key}"
            f"?X-Amz-Signature=mock_signature_{storage_key[:8]}&X-Amz-Expires={expires_timestamp}"
        )

    def delete_file(self, storage_key: str) -> bool:
        if storage_key in self.objects:
            del self.objects[storage_key]
            return True
        return False

    def file_exists(self, storage_key: str) -> bool:
        return storage_key in self.objects
