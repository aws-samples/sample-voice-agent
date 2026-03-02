"""
Daily API Client

Handles communication with Daily.co API for room management and token generation.
"""

import json
import logging
import os
from typing import Any
from urllib import request, error

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class DailyClient:
    """Client for Daily.co REST API."""

    API_BASE_URL = "https://api.daily.co/v1"

    def __init__(self, api_key: str | None = None):
        """
        Initialize Daily client.

        Args:
            api_key: Daily API key. If not provided, fetched from Secrets Manager.
        """
        self._api_key = api_key or self._get_api_key_from_secrets()
        if not self._api_key:
            raise ValueError("Daily API key not found")

    def _get_api_key_from_secrets(self) -> str | None:
        """Fetch Daily API key from AWS Secrets Manager."""
        secret_arn = os.environ.get("DAILY_API_KEY_SECRET_ARN")
        if not secret_arn:
            logger.warning("DAILY_API_KEY_SECRET_ARN not set")
            return None

        try:
            client = boto3.client("secretsmanager")
            response = client.get_secret_value(SecretId=secret_arn)
            secret_string = response.get("SecretString", "{}")
            secrets = json.loads(secret_string)
            return secrets.get("DAILY_API_KEY")
        except ClientError as e:
            logger.error(f"Failed to fetch Daily API key: {e}")
            raise

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
    ) -> dict:
        """
        Make HTTP request to Daily API.

        Args:
            method: HTTP method (GET, POST, DELETE)
            endpoint: API endpoint path
            data: Request body for POST requests

        Returns:
            JSON response from API

        Raises:
            ValueError: If API returns an error
        """
        url = f"{self.API_BASE_URL}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        body = json.dumps(data).encode("utf-8") if data else None

        req = request.Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with request.urlopen(req, timeout=30) as response:
                response_body = response.read().decode("utf-8")
                return json.loads(response_body) if response_body else {}
        except error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            logger.error(f"Daily API error: {e.code} - {error_body}")
            raise ValueError(f"Daily API error: {e.code} - {error_body}")
        except error.URLError as e:
            logger.error(f"Daily API connection error: {e}")
            raise ValueError(f"Daily API connection error: {e}")

    def create_room(
        self,
        name: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict:
        """
        Create a new Daily room.

        Args:
            name: Optional room name (auto-generated if not provided)
            properties: Room configuration properties

        Returns:
            Room details including url and name
        """
        data: dict[str, Any] = {}

        if name:
            data["name"] = name

        if properties:
            data["properties"] = properties

        logger.info(f"Creating Daily room: {name}")
        room = self._make_request("POST", "/rooms", data)
        logger.info(f"Created room: {room.get('name')} - {room.get('url')}")

        return room

    def get_room(self, room_name: str) -> dict:
        """
        Get room details by name.

        Args:
            room_name: Name of the room

        Returns:
            Room details
        """
        return self._make_request("GET", f"/rooms/{room_name}")

    def delete_room(self, room_name: str) -> dict:
        """
        Delete a room.

        Args:
            room_name: Name of the room to delete

        Returns:
            Deletion confirmation
        """
        logger.info(f"Deleting Daily room: {room_name}")
        return self._make_request("DELETE", f"/rooms/{room_name}")

    def create_meeting_token(
        self,
        room_name: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        """
        Create a meeting token for room access.

        Args:
            room_name: Name of the room
            properties: Token properties (permissions, expiry, etc.)

        Returns:
            Meeting token string
        """
        data: dict[str, Any] = {
            "properties": {
                "room_name": room_name,
            }
        }

        if properties:
            data["properties"].update(properties)

        logger.info(f"Creating meeting token for room: {room_name}")
        response = self._make_request("POST", "/meeting-tokens", data)
        return response.get("token", "")

    def get_sip_uri(self, room_name: str) -> str:
        """
        Get SIP URI for a room.

        The SIP URI is used to route PSTN calls into the Daily room.

        Args:
            room_name: Name of the room

        Returns:
            SIP URI string
        """
        # Daily SIP URIs follow this pattern
        # The actual domain may vary based on your Daily account configuration
        room = self.get_room(room_name)
        room_id = room.get("id", "")

        # Get SIP URI from room config if available
        # Room config contains the actual SIP endpoint for dial-in
        config = room.get("config", {})
        sip_uri_config = config.get("sip_uri", {})

        if sip_uri_config and "endpoint" in sip_uri_config:
            # Use the SIP endpoint from room config (includes .0 suffix)
            endpoint = sip_uri_config["endpoint"]
            sip_uri = f"sip:{endpoint}"
        else:
            # Fallback to constructing from room_id
            sip_domain = "daily-9d372c3e49636682-app.dapp.signalwire.com"
            sip_uri = f"sip:{room_id}@{sip_domain}"

        logger.info(f"SIP URI for {room_name}: {sip_uri}")

        return sip_uri

    def dial_out(
        self,
        room_name: str,
        phone_number: str,
        caller_id: str | None = None,
    ) -> dict:
        """
        Initiate outbound PSTN call from a Daily room.

        Args:
            room_name: Name of the room
            phone_number: Phone number to call (E.164 format)
            caller_id: Optional caller ID to display

        Returns:
            Dial-out response with call details
        """
        data: dict[str, Any] = {
            "room_name": room_name,
            "phone_number": phone_number,
        }

        if caller_id:
            data["caller_id"] = caller_id

        logger.info(f"Dialing out from {room_name} to {phone_number}")
        return self._make_request("POST", "/dialout", data)
