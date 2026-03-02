"""
Unit tests for Daily API client.

Run with: pytest test_daily_client.py -v
"""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

# Set environment variables before importing
os.environ['DAILY_API_KEY_SECRET_ARN'] = 'arn:aws:secretsmanager:us-east-1:123456789012:secret:test-secret'

from daily_client import DailyClient


class TestDailyClientInit(unittest.TestCase):
    """Tests for DailyClient initialization."""

    def test_init_with_api_key(self):
        """Should initialize with provided API key."""
        client = DailyClient(api_key='test-api-key')
        self.assertEqual(client._api_key, 'test-api-key')

    @patch('daily_client.boto3.client')
    def test_init_fetches_from_secrets_manager(self, mock_boto_client):
        """Should fetch API key from Secrets Manager when not provided."""
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {
            'SecretString': json.dumps({'DAILY_API_KEY': 'secret-key'})
        }
        mock_boto_client.return_value = mock_sm

        client = DailyClient()

        self.assertEqual(client._api_key, 'secret-key')
        mock_sm.get_secret_value.assert_called_once()

    def test_init_raises_without_api_key(self):
        """Should raise when no API key available."""
        # Remove env var and don't provide key
        with patch.dict(os.environ, {}, clear=True):
            with patch('daily_client.boto3.client') as mock_boto:
                mock_sm = MagicMock()
                mock_sm.get_secret_value.return_value = {
                    'SecretString': json.dumps({})  # No DAILY_API_KEY
                }
                mock_boto.return_value = mock_sm

                with self.assertRaises(ValueError):
                    DailyClient()


class TestDailyClientCreateRoom(unittest.TestCase):
    """Tests for DailyClient.create_room."""

    def setUp(self):
        """Set up test client."""
        self.client = DailyClient(api_key='test-api-key')

    @patch('daily_client.request.urlopen')
    def test_creates_room_with_name(self, mock_urlopen):
        """Should create room with specified name."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            'name': 'test-room',
            'url': 'https://test.daily.co/test-room',
            'id': 'room-123',
        }).encode('utf-8')
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        room = self.client.create_room(name='test-room')

        self.assertEqual(room['name'], 'test-room')
        self.assertIn('url', room)

    @patch('daily_client.request.urlopen')
    def test_creates_room_with_properties(self, mock_urlopen):
        """Should pass properties to Daily API."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            'name': 'test-room',
            'url': 'https://test.daily.co/test-room',
        }).encode('utf-8')
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        room = self.client.create_room(
            name='test-room',
            properties={'enable_chat': False, 'sip': {'enabled': True}}
        )

        # Verify the request was made
        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]
        request_body = json.loads(request_obj.data.decode('utf-8'))
        self.assertIn('properties', request_body)
        self.assertEqual(request_body['properties']['enable_chat'], False)


class TestDailyClientCreateMeetingToken(unittest.TestCase):
    """Tests for DailyClient.create_meeting_token."""

    def setUp(self):
        """Set up test client."""
        self.client = DailyClient(api_key='test-api-key')

    @patch('daily_client.request.urlopen')
    def test_creates_token_for_room(self, mock_urlopen):
        """Should create meeting token for specified room."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            'token': 'eyJ...',
        }).encode('utf-8')
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        token = self.client.create_meeting_token(room_name='test-room')

        self.assertEqual(token, 'eyJ...')

    @patch('daily_client.request.urlopen')
    def test_creates_token_with_properties(self, mock_urlopen):
        """Should pass token properties to API."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            'token': 'eyJ...',
        }).encode('utf-8')
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        token = self.client.create_meeting_token(
            room_name='test-room',
            properties={'is_owner': True, 'user_name': 'Bot'}
        )

        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]
        request_body = json.loads(request_obj.data.decode('utf-8'))
        self.assertTrue(request_body['properties']['is_owner'])
        self.assertEqual(request_body['properties']['user_name'], 'Bot')


class TestDailyClientGetSipUri(unittest.TestCase):
    """Tests for DailyClient.get_sip_uri."""

    def setUp(self):
        """Set up test client."""
        self.client = DailyClient(api_key='test-api-key')

    @patch('daily_client.request.urlopen')
    def test_returns_sip_uri(self, mock_urlopen):
        """Should return properly formatted SIP URI."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            'name': 'test-room',
            'id': 'abc-123-def',
        }).encode('utf-8')
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        sip_uri = self.client.get_sip_uri('test-room')

        self.assertEqual(sip_uri, 'sip:abc-123-def@sip.daily.co')


class TestDailyClientMakeRequest(unittest.TestCase):
    """Tests for DailyClient._make_request."""

    def setUp(self):
        """Set up test client."""
        self.client = DailyClient(api_key='test-api-key')

    @patch('daily_client.request.urlopen')
    def test_includes_auth_header(self, mock_urlopen):
        """Should include Authorization header."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{}'
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        self.client._make_request('GET', '/rooms')

        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]
        self.assertEqual(
            request_obj.get_header('Authorization'),
            'Bearer test-api-key'
        )

    @patch('daily_client.request.urlopen')
    def test_raises_on_http_error(self, mock_urlopen):
        """Should raise ValueError on HTTP error."""
        from urllib.error import HTTPError
        mock_urlopen.side_effect = HTTPError(
            url='https://api.daily.co/v1/rooms',
            code=401,
            msg='Unauthorized',
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": "Invalid API key"}')
        )

        with self.assertRaises(ValueError) as ctx:
            self.client._make_request('GET', '/rooms')

        self.assertIn('401', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
