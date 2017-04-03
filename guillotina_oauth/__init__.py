# -*- coding: utf-8 -*-
from guillotina import configure


def includeme(root):
    configure.permission('guillotina.GetOAuthGrant', 'Get OAuth Grant Code')
    configure.grant(
        permission="guillotina.GetOAuthGrant",
        role="guillotina.Anonymous")
    configure.scan('guillotina_oauth.oauth')
    configure.scan('guillotina_oauth.install')
