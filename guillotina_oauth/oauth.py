# -*- coding: utf-8 -*-
import asyncio
import json
import logging
import math
import os
import time
import typing as t
from calendar import timegm
from datetime import datetime
from os.path import join

import aiohttp
import aiohttp_client
import backoff
import jwt
from aiohttp.client_exceptions import ClientError
from aiohttp.web_exceptions import HTTPUnauthorized
from guillotina import app_settings
from guillotina import configure
from guillotina import task_vars
from guillotina.api.content import DefaultOPTIONS
from guillotina.async_util import IAsyncUtility
from guillotina.auth.users import GuillotinaUser
from guillotina.component import getUtility
from guillotina.exceptions import Unauthorized
from guillotina.interfaces import Allow
from guillotina.interfaces import IApplication
from guillotina.interfaces import IContainer
from guillotina.response import HTTPFailedDependency
from guillotina.response import Response
from guillotina.utils import get_current_request
from lru import LRU


logger = logging.getLogger("guillotina_oauth")

# Asyncio Utility
NON_IAT_VERIFY = {"verify_iat": False}

# cache user authorization for 1 minute so we don't hit oauth so much
try:
    USER_CACHE_DURATION = int(os.environ.get("USER_CACHE_DURATION", 60 * 2))
except (ValueError, TypeError):
    USER_CACHE_DURATION = 60 * 2

USER_CACHE = LRU(1000)

RETRIABLE_CODES = (484, 503)


class IOAuth(IAsyncUtility):
    """Marker interface for OAuth Utility."""

    pass


REST_API = {
    "get_authorization_code": ["POST", True],
    "get_service_token": ["POST", True],
    "valid_token": ["POST", True],
    "get_user": ["POST", False],
    "get_users": ["POST", False],
    "search_user": ["POST", False],
}


@configure.utility(provides=IOAuth)
class OAuth(object):
    """Object implementing OAuth Utility."""

    def __init__(self, settings=None, loop=None):
        self.loop = loop
        self._service_token = None
        self._settings = app_settings.get("oauth_settings", {})

    @property
    def configured(self):
        return (
            "server" in self._settings and "jwt_secret" in self._settings and "client_id" in self._settings,
            "client_password" in self._settings,
        )

    @property
    def attr_id(self):
        if "attr_id" in self._settings:
            return self._settings["attr_id"]
        else:
            return "mail"

    @property
    def server(self):
        return self._settings["server"]

    @property
    def client_id(self):
        return self._settings["client_id"]

    @property
    def client_password(self):
        return self._settings["client_password"]

    @property
    def conn_timeout(self):
        return self._settings["connect_timeout"]

    @property
    def timeout(self):
        return self._settings["request_timeout"]

    async def initialize(self, app=None):
        if self._settings.get("auto_renew_token") is False:
            return

        self.app = app
        if not self.configured:
            logger.debug("OAuth not configured")
            return

        while True:
            logger.debug("Renew token")
            now = timegm(datetime.utcnow().utctimetuple())
            try:
                await self.refresh_service_token()
                expiration = self._service_token["exp"]
                time_to_sleep = expiration - now - 60  # refresh before we run out of time...
                await asyncio.sleep(time_to_sleep)
            except asyncio.CancelledError:
                # we're good, die
                return
            except (aiohttp.client_exceptions.ClientConnectorError, ConnectionRefusedError):
                logger.debug("Could not connect to oauth host, oauth will not work")
                await asyncio.sleep(10)  # wait 10 seconds before trying again
            except Exception:
                logger.warn("Error renewing service token", exc_info=True)
                await asyncio.sleep(30)  # unknown error, try again in 30 seconds

    async def finalize(self, app=None):
        pass

    async def auth_code(self, scopes, client_id):
        result = await self.call_auth(
            "get_authorization_code",
            {
                "client_id": client_id,
                "service_token": await self.service_token,
                "scopes": scopes,
                "response_type": "code",
            },
        )
        if result:
            return result["auth_code"]
        return None

    async def refresh_service_token(self) -> str:
        logger.debug("Getting new service token")
        result = await self.call_auth(
            "get_service_token",
            {"client_id": self.client_id, "client_secret": self.client_password, "grant_type": "service"},
        )
        if result:
            self._service_token = result
            raw_service_token = self._service_token["service_token"]
            logger.debug(f"New service token issued: {raw_service_token[:10]}...")
            return raw_service_token
        else:
            logger.debug("No token returned from oauth")

    @property
    async def service_token(self) -> str:
        if self._service_token:
            now = timegm(datetime.utcnow().utctimetuple())
            if (self._service_token["exp"] - 60) > now:
                return self._service_token["service_token"]
        return await self.refresh_service_token()

    async def get_users(self, request):
        container = task_vars.container.get()
        scope = container.id
        header = {"Authorization": request.headers["Authorization"]}

        result = await self.call_auth(
            "get_users",
            params={"service_token": await self.service_token, "scope": scope, "photo_size": "false"},
            headers=header,
        )
        return result

    getUsers = get_users

    async def search_users(self, request, page=0, num_x_page=30, term="", search_attr=["mail"]):
        container = task_vars.container.get()
        scope = container.id
        header = {"Authorization": request.headers["Authorization"]}

        criteria = {}
        for attr in search_attr:
            criteria[attr] = f"{term}"

        payload = {
            "criteria": json.dumps(criteria),
            "exact_match": False,
            "attrs": json.dumps(search_attr),
            "page": page,
            "num_x_page": num_x_page,
            "service_token": await self.service_token,
            "scope": scope,
        }
        result = await self.call_auth("search_user", params=payload, headers=header)
        return result

    async def validate_token(self, request, token):
        container = task_vars.container.get()
        scope = container.id
        result = await self.call_auth(
            "valid_token", params={"code": await self.service_token, "token": token, "scope": scope}
        )
        if result:
            if "user" in result:
                return result["user"]
            else:
                return None
        return None

    async def get_temp_token(self, request, payload=None, ttl=None, clear=False, authorization=""):
        if payload is None:
            payload = {}
        container = task_vars.container.get()
        data = {
            "payload": payload,
            "service_token": await self.service_token,
            "scope": getattr(container, "id", None),
            "client_id": self.client_id,
            "clear": payload.pop("clear", clear),
        }
        if ttl:
            data["ttl"] = ttl
        if not authorization:
            authorization = request.headers.get("Authorization", "")
        async with aiohttp_client.post(
            join(self.server, "get_temp_token"),
            json=data,
            headers={"Authorization": authorization},
            timeout=self.timeout,
        ) as resp:
            text = await resp.text()
            if resp.status == 200:
                return text
            else:
                text = await resp.text()
                logger.warning("Error getting temp token: " f"{resp.status}: {text}", exc_info=True)

    async def grant_scope_roles(self, request, user, roles: t.Optional[t.List[str]] = None):
        roles = roles or []
        container = task_vars.container.get()
        async with aiohttp_client.post(
            join(self.server, "grant_scope_roles"),
            json={
                "scope": container.id,
                "user": user,
                "roles": roles,
                "service_token": await self.service_token,
            },
            headers={"Authorization": request.headers.get("Authorization", "")},
            timeout=self.timeout,
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                text = await resp.text()
                logger.warning("Error granting scope roles: " f"{resp.status}: {text}", exc_info=True)

    async def deny_scope_roles(self, request, user, roles: t.Optional[t.List[str]] = None):
        roles = roles or []
        container = task_vars.container.get()
        async with aiohttp_client.post(
            join(self.server, "deny_scope_roles"),
            json={"scope": container.id, "user": user, "roles": roles},
            headers={"Authorization": request.headers.get("Authorization", "")},
            timeout=self.timeout,
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                text = await resp.text()
                logger.warning("Error denying scope roles: " f"{resp.status}: {text}", exc_info=True)

    async def retrieve_temp_data(self, request, token):
        async with aiohttp_client.get(
            join(self.server, "retrieve_temp_data?token=" + token),
            headers={"Authorization": request.headers.get("Authorization", "")},
            timeout=self.timeout,
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                text = await resp.text()
                logger.warning("Error temp data: " f"{resp.status}: {text}", exc_info=True)

    async def check_scope_id(self, scope, service=False):
        request = get_current_request()
        data = {"id": scope}
        if service:
            data["service_token"] = await self.service_token
        url = join(self.server, "check_scope_id")
        async with aiohttp_client.get(
            url,
            params=data,
            headers={"Authorization": request.headers.get("Authorization", "")},
            timeout=self.timeout,
        ) as resp:
            try:
                return await resp.json()
            except Exception:
                text = await resp.text()
                logger.warning(
                    "Error getting response for check_scope_id: " f"{resp.status}: {text}", exc_info=True
                )

    async def get_user(self, username, scope, service=False):
        request = get_current_request()
        data = {
            "user": username,
            "service_token": await self.service_token,
            "scope": scope,
            "photo_size": "false",
        }
        if service:
            url = join(self.server, "service_get_user")
        else:
            url = join(self.server, "get_user")
        async with aiohttp_client.post(
            url,
            data=json.dumps(data),
            headers={"Authorization": request.headers.get("Authorization", "")},
            timeout=self.timeout,
        ) as resp:
            if resp.status == 200:
                return await resp.json()

    async def set_user_metadata(self, client_id, data):
        request = get_current_request()
        url = join(self.server, "edit_user")
        payload = {"client_id": client_id, "service_token": await self.service_token, "info": {"data": data}}

        async with aiohttp_client.post(
            url,
            data=json.dumps(payload),
            headers={"Authorization": request.headers.get("Authorization", "")},
            timeout=self.timeout,
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.warning("Error setting user metadata: " f"{resp.status}: {text}", exc_info=True)

            return resp.status

    async def set_account_metadata(self, scope, payload, client_id, service=False):
        request = get_current_request()
        data = {"scope": scope, "payload": payload, "client_id": client_id}
        if service:
            data["service_token"] = await self.service_token
            url = join(self.server, "service_set_account_metadata")
        else:
            url = join(self.server, "set_account_metadata")
        async with aiohttp_client.post(
            url,
            data=json.dumps(data),
            headers={"Authorization": request.headers.get("Authorization", "")},
            timeout=self.timeout,
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                text = await resp.text()
                logger.warning("Error setting account metadata: " f"{resp.status}: {text}", exc_info=True)

    async def modify_limit(self, scope, name, value, client_id="", service=False):
        request = get_current_request()
        data = {"scope": scope, "name": name, "value": value, "client_id": client_id}
        if service:
            data["service_token"] = await self.service_token
            url = join(self.server, "service_modify_scope_limit")
        else:
            url = join(self.server, "modify_scope_limit")
        async with aiohttp_client.post(
            url,
            data=json.dumps(data),
            headers={"Authorization": request.headers.get("Authorization", "")},
            timeout=self.timeout,
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                text = await resp.text()
                logger.warning("Error modifying limit: " f"{resp.status}: {text}", exc_info=True)

    async def get_account_metadata(self, scope, client_id="", service=False):
        request = get_current_request()
        data = {"scope": scope, "client_id": client_id}
        if service:
            data["service_token"] = await self.service_token
            url = join(self.server, "get_metadata_by_service")
        else:
            url = join(self.server, "get_metadata")
        async with aiohttp_client.post(
            url,
            data=json.dumps(data),
            headers={"Authorization": request.headers.get("Authorization", "")},
            timeout=self.timeout,
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                text = await resp.text()
                logger.warning("Error getting metadata: " f"{resp.status}: {text}", exc_info=True)

    async def add_scope(self, scope, admin_user, urls=None):
        if urls is None:
            urls = {}
        request = get_current_request()
        data = {
            "admin_user": admin_user,
            "service_token": await self.service_token,
            "scope": scope,
            "urls": urls,
        }
        url = join(self.server, "add_scope")
        async with aiohttp_client.post(
            url,
            data=json.dumps(data),
            headers={"Authorization": request.headers.get("Authorization", "")},
            timeout=self.timeout,
        ) as resp:
            if resp.status == 200:
                try:
                    return await resp.json()
                except Exception:
                    pass
            text = await resp.text()
            logger.warning("Error adding scope: " f"{resp.status}: {text}", exc_info=True)

    async def add_user(
        self,
        username,
        email,
        password,
        send_email=True,
        reset_password=False,
        roles=None,
        data=None,
        cn=None,
        sn=None,
    ):
        if data is None:
            data = {}
        request = get_current_request()
        container = task_vars.container.get()
        data = {
            "user": username,
            "email": email,
            "cn": cn,
            "sn": sn,
            "password": password,
            "service_token": await self.service_token,
            "client_id": self.client_id,
            "send-email": send_email,
            "reset-password": reset_password,
            "scope": getattr(container, "id", None),
            "data": data,
        }
        if roles:
            data["roles"] = roles
        headers = {"Authorization": request.headers.get("Authorization", "")}
        async with aiohttp_client.post(
            join(self.server, "add_user"), data=json.dumps(data), timeout=self.timeout, headers=headers
        ) as resp:
            if resp.status == 200:
                return resp.status, await resp.json()
            else:
                return resp.status, await resp.text()

    @backoff.on_exception(backoff.expo, (OSError, ClientError), max_time=5, max_tries=4)
    async def call_auth(
        self, url: str, params: dict, headers: t.Optional[dict] = None, future=None, retries: int = 0, **kw
    ):
        headers = headers or {}
        method, needs_decode = REST_API[url]

        full_url = join(self.server.rstrip("/"), url.strip("/"))
        result = None
        text = "unknown"
        if method == "GET":
            logger.debug("GET " + full_url)
            async with aiohttp_client.get(
                full_url, params=params, headers=headers, timeout=self.timeout
            ) as resp:
                if resp.status == 200:
                    try:
                        result = jwt.decode(
                            await resp.text(),
                            app_settings["jwt"]["secret"],
                            algorithms=[app_settings["jwt"]["algorithm"]],
                        )
                    except jwt.InvalidIssuedAtError:
                        logger.error("Error on Time at OAuth Server")
                        result = jwt.decode(
                            await resp.text(),
                            app_settings["jwt"]["secret"],
                            algorithms=[app_settings["jwt"]["algorithm"]],
                            options=NON_IAT_VERIFY,
                        )
                else:
                    text = await resp.text()
        elif method == "POST":

            logger.debug("POST " + full_url)
            async with aiohttp_client.post(
                full_url, data=json.dumps(params), headers=headers, timeout=self.timeout
            ) as resp:
                if resp.status == 200:
                    if needs_decode:
                        try:
                            result = jwt.decode(
                                await resp.text(),
                                app_settings["jwt"]["secret"],
                                algorithms=[app_settings["jwt"]["algorithm"]],
                            )
                        except jwt.InvalidIssuedAtError:
                            logger.error("Error on Time at OAuth Server")
                            result = jwt.decode(
                                await resp.text(),
                                app_settings["jwt"]["secret"],
                                algorithms=[app_settings["jwt"]["algorithm"]],
                                options=NON_IAT_VERIFY,
                            )
                    else:
                        result = await resp.json()
                else:
                    text = await resp.text()
        if resp.status != 200:
            try:
                if resp.status in RETRIABLE_CODES:
                    if retries < 3:
                        logger.warning(f"OAUTH SERVER ERROR({url}) {resp.status} {text}, retrying")
                        if resp.status == 484:  # bad service token status code
                            logger.warning("Invalid service token, refreshing")
                            # try to get new one and retry this...
                            await self.refresh_service_token()
                        else:
                            # provide brief pause before retrying
                            await asyncio.sleep(0.05)
                        return await self.call_auth(
                            url, params, headers=headers, future=future, retries=retries + 1, **kw
                        )
                    else:
                        logger.warning(f"OAUTH SERVER ERROR({url}) {resp.status} {text}, retries exhausted")
                        raise HTTPFailedDependency(
                            content={
                                "reason": "oauthServerFailure",
                                "message": "Failed to call oauth server",
                                "retries": retries,
                                "status": resp.status,
                                "text": text,
                            }
                        )
                elif resp.status >= 500:
                    raise HTTPFailedDependency(
                        content={
                            "reason": "oauthServerFailure",
                            "message": "Unhandled oauth server error",
                            "retries": retries,
                            "status": resp.status,
                            "text": text,
                        }
                    )
            except HTTPFailedDependency:
                raise
            except Exception:
                logger.error(f"UNHANDLED OAUTH SERVER ERROR({url}) {resp.status}", exc_info=True)
                raise HTTPFailedDependency(
                    content={"reason": "oauthServerFailure", "message": "Failed to call oauth server"}
                )

        if future is not None:
            future.set_result(result)
        else:
            return result


class OAuthJWTValidator:

    for_validators = ("bearer", "wstoken")

    def __init__(self):
        pass

    def get_user_cache_key(self, login, token):
        container = task_vars.container.get()
        return "{}::{}::{}::{}".format(
            getattr(container, "id", "root"),
            login,
            token,
            math.ceil(math.ceil(time.time()) / USER_CACHE_DURATION),
        )

    async def validate(self, token):
        """Return the user from the token."""
        if token.get("type") not in ("bearer", "wstoken"):
            return None

        if "." not in token.get("token", ""):
            # quick way to check if actually might be jwt
            return None

        try:
            try:
                validated_jwt = jwt.decode(
                    token["token"],
                    app_settings["jwt"]["secret"],
                    algorithms=[app_settings["jwt"]["algorithm"]],
                )
            except jwt.exceptions.ExpiredSignatureError:
                logger.warning("Token Expired")
                raise HTTPUnauthorized()
            except jwt.InvalidIssuedAtError:
                logger.warning("Back to the future")
                validated_jwt = jwt.decode(
                    token["token"],
                    app_settings["jwt"]["secret"],
                    algorithms=[app_settings["jwt"]["algorithm"]],
                    options=NON_IAT_VERIFY,
                )

            try:
                token["id"] = validated_jwt["login"]
            except KeyError:
                # somehow got valid jwt but it didn't have correct info. Ignore
                return None

            cache_key = self.get_user_cache_key(validated_jwt["login"], validated_jwt["token"])
            if cache_key in USER_CACHE:
                return USER_CACHE[cache_key]

            oauth_utility = getUtility(IOAuth)

            # Enable extra validation
            # validation = await oauth_utility.validate_token(
            #    self.request, validated_jwt['token'])
            # if validation is not None and \
            #        validation == validated_jwt['login']:
            #    # We validate that the actual token belongs to the same
            #    # as the user on oauth

            container = task_vars.container.get()
            scope = getattr(container, "id", "root")
            # service_token = await oauth_utility.service_token
            t1 = time.time()
            try:
                result = await oauth_utility.call_auth(
                    "get_user",
                    params={
                        # 'service_token': service_token,
                        # 'user_token': validated_jwt['token'],
                        "scope": scope,
                        "user": validated_jwt["login"],
                        "photo_size": "false",
                    },
                    headers={"Authorization": "Bearer " + token["token"]},
                )
            except asyncio.TimeoutError:
                raise HTTPFailedDependency(
                    content={"reason": "userApiTimeout", "message": "Timeout authenticating with user api"}
                )

            tdif = t1 - time.time()
            logger.info("Time OAUTH %f" % tdif)
            if result:
                try:
                    user = OAuthGuillotinaUser(result, oauth_utility.attr_id)
                except Unauthorized:
                    return None

                user.name = validated_jwt["name"]
                user.token = validated_jwt["token"]
                if user and user.id == token["id"]:
                    USER_CACHE[cache_key] = user
                    return user

        except jwt.exceptions.DecodeError:
            pass

        return None


class OAuthGuillotinaUser(GuillotinaUser):
    def __init__(self, data, attr_id="mail"):
        super(OAuthGuillotinaUser, self).__init__()
        self._attr_id = attr_id
        self._init_data(data)
        self._properties = {}
        self.data = data

    def _init_data(self, user_data):
        self._roles = {}
        for key in user_data["roles"]:
            self._roles[key] = Allow
        self._groups = [key for key in user_data["groups"]]
        self.id = user_data[self._attr_id]
        for permission in user_data.get("permissions") or []:
            self._permissions[permission] = Allow


@configure.service(
    context=IApplication,
    name="@oauthgetcode",
    method="POST",
    permission="guillotina.GetOAuthGrant",
    allow_access=True,
)
@configure.service(
    context=IContainer,
    name="@oauthgetcode",
    method="POST",
    permission="guillotina.GetOAuthGrant",
    allow_access=True,
)
@configure.service(
    context=IApplication,
    name="@oauthgetcode",
    method="GET",
    permission="guillotina.GetOAuthGrant",
    allow_access=True,
)
@configure.service(
    context=IContainer,
    name="@oauthgetcode",
    method="GET",
    permission="guillotina.GetOAuthGrant",
    allow_access=True,
    summary="Grant access with OAuth 2.0",
    description="Authenticate with [OAuth 2.0](https://oauth.net/)",
)
async def oauth_get_code(context, request):
    oauth_utility = getUtility(IOAuth)
    if "client_id" in request.query:
        client_id = request.query["client_id"]
    else:
        client_id = oauth_utility.client_id

    scopes = []
    if hasattr(request, "_container_id"):
        scopes.append(request._container_id)
    elif "scope" in request.query:
        scopes.append(request.query["scope"])

    result = await oauth_utility.auth_code(scopes, client_id)
    return {"auth_code": result}


@configure.service(
    context=IContainer, name="@oauthgetcode", method="OPTIONS", permission="guillotina.GetOAuthGrant"
)
class OptionsGetCredentials(DefaultOPTIONS):
    async def __call__(self):
        headers = {}
        allowed_headers = ["Content-Type"] + app_settings["cors"]["allow_headers"]
        headers["Access-Control-Allow-Headers"] = ",".join(allowed_headers)
        headers["Access-Control-Allow-Methods"] = ",".join(app_settings["cors"]["allow_methods"])
        headers["Access-Control-Max-Age"] = str(app_settings["cors"]["max_age"])
        headers["Access-Control-Allow-Origin"] = ",".join(app_settings["cors"]["allow_origin"])
        headers["Access-Control-Allow-Credentials"] = "True"
        headers["Access-Control-Expose-Headers"] = ", ".join(app_settings["cors"]["allow_headers"])

        resp = await oauth_get_code(self.context, self.request)
        return Response(content=resp, headers=headers, status=200)
