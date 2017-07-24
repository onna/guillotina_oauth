.. contents::

GUILLOTINA_OAUTH
================


WARNING: development of this package has ceased...


Features
--------

 * There is no persistence information about the user

 * The configuration is global for all application


Configuration
-------------

Generic global configuration on guillotina utilities section:

{
    "applicatoins": ["guillotina_oauth"],
    "auth_token_validators": [
        "guillotina.auth.validators.SaltedHashPasswordValidator",
        "guillotina_oauth.oauth.OAuthJWTValidator"
    ],
    "oauth_settings": {
        "server": "http://localhost/",
        "jwt_secret": "secret",
        "jwt_algorithm": "HS256",
        "client_id": 11,
        "client_password": "secret"
    }
}
