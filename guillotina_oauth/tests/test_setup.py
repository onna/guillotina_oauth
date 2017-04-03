# -*- coding: utf-8 -*-
from guillotina_oauth.oauth import IOAuth
from guillotina.component import getUtility


def test_auth_registered(dummy_guillotina):
    assert getUtility(IOAuth) is not None
