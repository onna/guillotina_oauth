from guillotina.testing import TESTING_SETTINGS

pytest_plugins = ["guillotina.tests.fixtures"]

TESTING_SETTINGS["applications"] = ["guillotina_oauth"]
TESTING_SETTINGS["oauth_settings"] = {
    "server": "http://localhost/",
    "jwt_secret": "secret",
    "jwt_algorithm": "HS256",
    "client_id": 11,
    "client_password": "secret",
}
