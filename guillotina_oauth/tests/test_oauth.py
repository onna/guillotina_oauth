from unittest.mock import patch

import pytest as pytest
from aioresponses import aioresponses
from guillotina.component import get_utility
from guillotina_oauth.oauth import IOAuth
from guillotina_oauth.oauth import OAuth


class MockRequest:
    def __init__(self, mock_headers=None):
        self.headers = mock_headers or {}


async def mock_service_token():
    return "test_value"


@pytest.mark.asyncio
async def test_should_set_user_metadata(dummy_guillotina):
    with aioresponses() as mock:
        json_obj = {
            "test": "1",
            "jpegPhoto": "",
        }
        mock.post("http://localhost/edit_user", payload=json_obj, status=200)
        oauth_utility = get_utility(IOAuth)

        with patch("guillotina_oauth.oauth.get_current_request", return_value=MockRequest()):
            with patch.object(OAuth, "refresh_service_token", return_value="test"):
                resp = await oauth_utility.set_user_metadata("canonical", {"test": "1"})

                assert resp == 200
