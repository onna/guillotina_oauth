# -*- coding: utf-8 -*-
import pytest
from guillotina.component import getUtility

from guillotina_oauth.oauth import IOAuth


pytestmark = pytest.mark.asyncio


async def test_auth_registered(dummy_guillotina):
    assert getUtility(IOAuth) is not None
