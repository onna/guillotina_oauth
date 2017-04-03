.. contents::

GUILLOTINA_OAUTH
================


Features
--------

 * There is no persistence information about the user

 * The configuration is global for all application


Configuration
-------------

Generic global configuration on guillotina utilities section:

{
    "applicatoins": ["guillotina_oauth"],
    "oauth_settings": {
        "server": "http://localhost/",
        "jwt_secret": "secret",
        "jwt_algorithm": "HS256",
        "client_id": 11,
        "client_password": "secret"
    }
}


Installation on a site
----------------------

POST SITE_URL/@install

{
	'pluggins': [
		'guillotina.googleoauth'
	]
}

Uninstall on a site
-------------------

POST SITE_URL/@uninstall

{
	'pluggins': [
		'guillotina.googleoauth'
	]
}


Events
------

guillotina.auth.events.NewUserLogin
