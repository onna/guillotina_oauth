from aioresponses import aioresponses
from guillotina.component import get_utility

from guillotina_oauth.oauth import IOAuth, OAuth

from unittest.mock import patch


class MockRequest:
    def __init__(self, mock_headers=None):
        self.headers = mock_headers or {}


async def mock_service_token():
    return "test_value"


async def test_should_set_user_metadata(dummy_guillotina):
    with aioresponses() as mock:
        mock.post("http://localhost/edit_user")
        oauth_utility = get_utility(IOAuth)

        with patch("guillotina_oauth.oauth.get_current_request", return_value=MockRequest()):
            with patch.object(OAuth, "refresh_service_token", return_value="test"):
                resp = await oauth_utility.set_user_metadata("canonical", {"test": "1"})

                assert resp == 200
