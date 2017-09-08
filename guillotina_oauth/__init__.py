# -*- coding: utf-8 -*-
from guillotina import configure


app_settings = {
    "oauth_settings": {
        "connect_timeout": 5,
        "request_timeout": 30,
        'auto_renew_token': True
    }
}


def includeme(root):
    configure.permission('guillotina.GetOAuthGrant', 'Get OAuth Grant Code')
    configure.grant(
        permission="guillotina.GetOAuthGrant",
        role="guillotina.Anonymous")
    configure.scan('guillotina_oauth.oauth')
    configure.scan('guillotina_oauth.install')
