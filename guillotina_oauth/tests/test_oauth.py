from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest as pytest
from aioresponses import aioresponses
from guillotina.component import get_utility
from guillotina_oauth.oauth import IOAuth
from guillotina_oauth.oauth import OAuth


class MockRequest:
    def __init__(self, mock_headers=None):
        self.headers = mock_headers or {}


@pytest.mark.asyncio
async def test_should_set_user_metadata(dummy_guillotina):
    with aioresponses() as mock:
        json_obj = {"test": "1"}
        mock.post("http://localhost/edit_user", payload=json_obj, status=200)
        oauth_utility = get_utility(IOAuth)

        with patch("guillotina_oauth.oauth.get_current_request", return_value=MockRequest()):
            with patch.object(OAuth, "refresh_service_token", new_callable=AsyncMock, return_value="test"):
                resp = await oauth_utility.set_user_metadata("canonical", {"test": "1"})

                assert resp == 200


@pytest.mark.asyncio
async def test_get_account_metadata_retries_on_484(dummy_guillotina):
    with aioresponses() as mock:
        mock.post("http://localhost/get_metadata_by_service", status=484)
        mock.post(
            "http://localhost/get_metadata_by_service",
            payload={"parent_site_id": "parent"},
            status=200,
        )
        oauth_utility = get_utility(IOAuth)

        with patch("guillotina_oauth.oauth.get_current_request", return_value=MockRequest()):
            with patch.object(OAuth, "refresh_service_token", new_callable=AsyncMock, return_value="new-token"):
                result = await oauth_utility.get_account_metadata("child", service=True)

        assert result == {"parent_site_id": "parent"}
