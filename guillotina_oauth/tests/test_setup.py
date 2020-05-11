# -*- coding: utf-8 -*-
from guillotina.component import getUtility

from guillotina_oauth.oauth import IOAuth
import pytest

pytestmark = pytest.mark.asyncio


async def test_auth_registered(dummy_guillotina):
    assert getUtility(IOAuth) is not None
