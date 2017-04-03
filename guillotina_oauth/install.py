# -*- coding: utf-8 -*-
from guillotina import configure
from guillotina.addons import Addon
from guillotina.interfaces import ILayers


POAUTH_LAYER = 'guillotina_oauth.interfaces.IPOAuthLayer'


@configure.addon(
    name="poauth",
    title="Plone OAuth Login")
class POauthAddon(Addon):

    @classmethod
    def install(cls, site, request):
        registry = request.site_settings
        registry.forInterface(ILayers).active_layers |= {
            POAUTH_LAYER
        }

    @classmethod
    def uninstall(cls, site, request):
        registry = request.site_settings
        registry.forInterface(ILayers).active_layers -= {
            POAUTH_LAYER
        }
