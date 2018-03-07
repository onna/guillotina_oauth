# -*- coding: utf-8 -*-
from aiohttp.web_exceptions import HTTPUnauthorized
from calendar import timegm
from datetime import datetime
from guillotina import app_settings
from guillotina import configure
from guillotina.api.content import DefaultOPTIONS
from guillotina.async import IAsyncUtility
from guillotina.auth.users import GuillotinaUser
from guillotina.browser import Response
from guillotina.component import getUtility
from guillotina.exceptions import Unauthorized
from guillotina.interfaces import Allow
from guillotina.interfaces import IApplication
from guillotina.interfaces import IContainer
from guillotina.utils import get_current_request
from lru import LRU

import aiohttp
import asyncio
import json
import jwt
import logging
import math
import time


logger = logging.getLogger('guillotina_oauth')

# Asyncio Utility
NON_IAT_VERIFY = {
    'verify_iat': False,
}

# cache user authorization for 1 minute so we don't hit oauth so much
USER_CACHE_DURATION = 60 * 1
USER_CACHE = LRU(1000)


class IOAuth(IAsyncUtility):
    """Marker interface for OAuth Utility."""

    pass


REST_API = {
    'get_authorization_code': ['POST', True],
    'get_service_token': ['POST', True],
    'valid_token': ['POST', True],
    'get_user': ['POST', False],
    'get_users': ['POST', False],
    'search_user': ['POST', False]
}


@configure.utility(provides=IOAuth)
class OAuth(object):
    """Object implementing OAuth Utility."""

    def __init__(self, settings=None, loop=None):
        self.loop = loop
        self._service_token = None
        self._settings = app_settings.get('oauth_settings', {})

    @property
    def configured(self):
        return ('server' in self._settings and
                'jwt_secret' in self._settings and
                'client_id' in self._settings,
                'client_password' in self._settings)

    @property
    def attr_id(self):
        if 'attr_id' in self._settings:
            return self._settings['attr_id']
        else:
            return 'mail'

    @property
    def server(self):
        return self._settings['server']

    @property
    def client_id(self):
        return self._settings['client_id']

    @property
    def client_password(self):
        return self._settings['client_password']

    @property
    def conn_timeout(self):
        return self._settings['connect_timeout']

    @property
    def timeout(self):
        return self._settings['request_timeout']

    async def initialize(self, app=None):
        if self._settings.get('auto_renew_token') is False:
            return

        self.app = app
        if not self.configured:
            logger.debug('OAuth not configured')
            return

        while True:
            logger.debug('Renew token')
            now = timegm(datetime.utcnow().utctimetuple())
            try:
                await self.refresh_service_token()
                expiration = self._service_token['exp']
                time_to_sleep = expiration - now - 60  # refresh before we run out of time...
                await asyncio.sleep(time_to_sleep)
            except asyncio.CancelledError:
                # we're good, die
                return
            except (aiohttp.client_exceptions.ClientConnectorError,
                    ConnectionRefusedError):
                logger.debug('Could not connect to oauth host, oauth will not work')
                await asyncio.sleep(10)  # wait 10 seconds before trying again
            except:
                logger.warn('Error renewing service token', exc_info=True)
                await asyncio.sleep(30)  # unknown error, try again in 30 seconds

    async def finalize(self, app=None):
        pass

    async def auth_code(self, scopes, client_id):
        result = await self.call_auth('get_authorization_code', {
            'client_id': client_id,
            'service_token': await self.service_token,
            'scopes': scopes,
            'response_type': 'code'
        })
        if result:
            return result['auth_code']
        return None

    async def refresh_service_token(self):
        logger.debug('Getting new service token')
        result = await self.call_auth('get_service_token', {
            'client_id': self.client_id,
            'client_secret': self.client_password,
            'grant_type': 'service'
        })
        if result:
            self._service_token = result
            raw_service_token = self._service_token['service_token']
            logger.debug(f'New service token issued: {raw_service_token[:10]}...')
            return raw_service_token
        else:
            logger.debug('No token returned from oauth')

    @property
    async def service_token(self):
        if self._service_token:
            now = timegm(datetime.utcnow().utctimetuple())
            if (self._service_token['exp'] - 60) > now:
                return self._service_token['service_token']
        return await self.refresh_service_token()

    async def get_users(self, request):
        scope = request.container.id
        header = {
            'Authorization': request.headers['Authorization']
        }

        result = await self.call_auth(
            'get_users',
            params={
                'service_token': await self.service_token,
                'scope': scope
            },
            headers=header
        )
        return result
    getUsers = get_users

    async def search_users(self, request, page=0, num_x_page=30, term='', search_attr='mail'):
        scope = request.container.id
        header = {
            'Authorization': request.headers['Authorization']
        }

        criteria = {search_attr: f"{term}*"}
        payload = {
            'criteria': json.dumps(criteria),
            'exact_match': False,
            'attrs': f'["{search_attr}"]',
            'page': page,
            'num_x_page': num_x_page,
            'service_token': await self.service_token,
            'scope': scope
        }
        result = await self.call_auth(
            'search_user',
            params=payload,
            headers=header
        )
        return result

    async def validate_token(self, request, token):
        scope = request.container.id
        result = await self.call_auth(
            'valid_token',
            params={
                'code': await self.service_token,
                'token': token,
                'scope': scope
            }
        )
        if result:
            if 'user' in result:
                return result['user']
            else:
                return None
        return None

    async def get_temp_token(self, request, payload={}, ttl=None, clear=False):
        request = get_current_request()
        data = {
            'payload': payload,
            'service_token': await self.service_token,
            'scope': request._container_id,
            'client_id': self.client_id,
            'clear': payload.pop('clear', clear)
        }
        if ttl:
            data['ttl'] = ttl
        with aiohttp.ClientSession(conn_timeout=self.conn_timeout) as session:
            async with session.post(
                    self.server + 'get_temp_token',
                    json=data,
                    headers={
                        'Authorization': request.headers.get('Authorization', '')
                    },
                    timeout=self.timeout) as resp:
                text = await resp.text()
                if resp.status == 200:
                    return text

    async def grant_scope_roles(self, request, user, roles=[]):
        request = get_current_request()
        with aiohttp.ClientSession(conn_timeout=self.conn_timeout) as session:
            async with session.post(
                    self.server + 'grant_scope_roles',
                    json={
                        "scope": request.container.id,
                        "user": user,
                        "roles": roles,
                        'service_token': await self.service_token,
                    },
                    headers={
                        'Authorization': request.headers.get('Authorization', '')
                    },
                    timeout=self.timeout) as resp:
                if resp.status == 200:
                    return await resp.json()

    async def deny_scope_roles(self, request, user, roles=[]):
        request = get_current_request()
        with aiohttp.ClientSession(conn_timeout=self.conn_timeout) as session:
            async with session.post(
                    self.server + 'deny_scope_roles',
                    json={
                        "scope": request.container.id,
                        "user": user,
                        "roles": roles
                    },
                    headers={
                        'Authorization': request.headers.get('Authorization', '')
                    },
                    timeout=self.timeout) as resp:
                if resp.status == 200:
                    return await resp.json()

    async def retrieve_temp_data(self, request, token):
        request = get_current_request()
        with aiohttp.ClientSession(conn_timeout=self.conn_timeout) as session:
            async with session.get(
                    self.server + 'retrieve_temp_data?token=' + token,
                    headers={
                        'Authorization': request.headers.get('Authorization', '')
                    },
                    timeout=self.timeout) as resp:
                if resp.status == 200:
                    return await resp.json()

    async def get_user(self, username, scope):
        request = get_current_request()
        data = {
            'user': username,
            'service_token': await self.service_token,
            'scope': scope
        }
        with aiohttp.ClientSession(conn_timeout=self.conn_timeout) as session:
            async with session.post(
                    self.server + 'get_user',
                    data=json.dumps(data),
                    headers={
                        'Authorization': request.headers.get('Authorization', '')
                    },
                    timeout=self.timeout) as resp:
                if resp.status == 200:
                    return await resp.json()

    async def add_user(self, username, email, password, send_email=True,
                       reset_password=False, roles=None):
        request = get_current_request()
        data = {
            'user': username,
            'email': email,
            'password': password,
            'service_token': await self.service_token,
            'send-email': send_email,
            'reset-password': reset_password,
            'scope': getattr(request, '_container_id', None)
        }
        if roles:
            data['roles'] = roles
        headers = {
            'Authorization': request.headers.get('Authorization', '')
        }
        with aiohttp.ClientSession(conn_timeout=self.conn_timeout) as session:
            async with session.post(
                    self.server + 'add_user',
                    data=json.dumps(data),
                    timeout=self.timeout,
                    headers=headers) as resp:
                if resp.status == 200:
                    return resp.status, await resp.json()
                else:
                    return resp.status, await resp.text()

    async def call_auth(self, url, params, headers={}, future=None,
                        retry=False, **kw):
        method, needs_decode = REST_API[url]

        result = None
        with aiohttp.ClientSession(conn_timeout=self.conn_timeout) as session:
            if method == 'GET':
                logger.debug('GET ' + self.server + url)
                async with session.get(
                        self.server + url,
                        params=params,
                        headers=headers,
                        timeout=self.timeout) as resp:
                    if resp.status == 200:
                        try:
                            result = jwt.decode(
                                await resp.text(),
                                app_settings['jwt']['secret'],
                                algorithms=[app_settings['jwt']['algorithm']])
                        except jwt.InvalidIssuedAtError:
                            logger.error('Error on Time at OAuth Server')
                            result = jwt.decode(
                                await resp.text(),
                                app_settings['jwt']['secret'],
                                algorithms=[app_settings['jwt']['algorithm']],
                                options=NON_IAT_VERIFY)
            elif method == 'POST':
                logger.debug('POST ' + self.server + url)
                async with session.post(
                        self.server + url,
                        data=json.dumps(params),
                        headers=headers,
                        timeout=self.timeout) as resp:
                    if resp.status == 200:
                        if needs_decode:
                            try:
                                result = jwt.decode(
                                    await resp.text(),
                                    app_settings['jwt']['secret'],
                                    algorithms=[app_settings['jwt']['algorithm']])
                            except jwt.InvalidIssuedAtError:
                                logger.error('Error on Time at OAuth Server')
                                result = jwt.decode(
                                    await resp.text(),
                                    app_settings['jwt']['secret'],
                                    algorithms=[app_settings['jwt']['algorithm']],
                                    options=NON_IAT_VERIFY)
                        else:
                            result = await resp.json()
            if resp.status != 200:
                # handle the error...
                text = await resp.text()
                if resp.status == 484 and not retry:  # bad service token status code
                    logger.error('Invalid service token, refreshing')
                    # try to get new one and retry this...
                    await self.refresh_service_token()
                    await resp.release()
                    session.close()
                    return await self.call_auth(url, params, headers=headers,
                                                future=future, retry=True, **kw)
                else:
                    logger.error(
                        f'OAUTH SERVER ERROR({url}) {resp.status} {text}')
            await resp.release()
            session.close()
        if future is not None:
            future.set_result(result)
        else:
            return result


class OAuthJWTValidator(object):

    for_validators = ('bearer', 'wstoken')

    def __init__(self, request):
        self.request = request

    def get_user_cache_key(self, login):
        return '{}-{}-{}'.format(
            getattr(self.request, '_container_id', 'root'),
            login,
            math.ceil(math.ceil(time.time()) / USER_CACHE_DURATION)
        )

    async def validate(self, token):
        """Return the user from the token."""
        if token.get('type') not in ('bearer', 'wstoken'):
            return None

        if '.' not in token.get('token', ''):
            # quick way to check if actually might be jwt
            return None

        try:
            try:
                validated_jwt = jwt.decode(
                    token['token'],
                    app_settings['jwt']['secret'],
                    algorithms=[app_settings['jwt']['algorithm']])
            except jwt.exceptions.ExpiredSignatureError:
                logger.warn("Token Expired")
                raise HTTPUnauthorized()
            except jwt.InvalidIssuedAtError:
                logger.warn("Back to the future")
                validated_jwt = jwt.decode(
                    token['token'],
                    app_settings['jwt']['secret'],
                    algorithms=[app_settings['jwt']['algorithm']],
                    options=NON_IAT_VERIFY)

            token['id'] = validated_jwt['login']

            cache_key = self.get_user_cache_key(validated_jwt['token'])
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

            scope = getattr(self.request, '_container_id', 'root')
            service_token = await oauth_utility.service_token
            t1 = time.time()
            result = await oauth_utility.call_auth(
                'get_user',
                params={
                    'service_token': service_token,
                    # 'user_token': validated_jwt['token'],
                    'scope': scope,
                    'user': validated_jwt['login']
                },
                headers={
                    'Authorization': 'Bearer ' + token['token']
                }
            )
            tdif = t1 - time.time()
            logger.info('Time OAUTH %f' % tdif)
            if result:
                try:
                    user = OAuthGuillotinaUser(
                        self.request, result, oauth_utility.attr_id)
                except Unauthorized:
                    return None

                user.name = validated_jwt['name']
                user.token = validated_jwt['token']
                if user and user.id == token['id']:
                    USER_CACHE[cache_key] = user
                    return user

        except jwt.exceptions.DecodeError:
            pass

        return None


class OAuthGuillotinaUser(GuillotinaUser):

    def __init__(self, request, data, attr_id='mail'):
        super(OAuthGuillotinaUser, self).__init__(request)
        self._attr_id = attr_id
        self._init_data(data)
        self._properties = {}
        self.data = data

    def _init_data(self, user_data):
        self._roles = {}
        for key in user_data['roles']:
            self._roles[key] = Allow
        self._groups = [key for key
                        in user_data['groups']]
        self.id = user_data[self._attr_id]


@configure.service(context=IApplication, name='@oauthgetcode', method='POST',
                   permission='guillotina.GetOAuthGrant', allow_access=True)
@configure.service(context=IContainer, name='@oauthgetcode', method='POST',
                   permission='guillotina.GetOAuthGrant', allow_access=True)
@configure.service(context=IApplication, name='@oauthgetcode', method='GET',
                   permission='guillotina.GetOAuthGrant', allow_access=True)
@configure.service(context=IContainer, name='@oauthgetcode', method='GET',
                   permission='guillotina.GetOAuthGrant', allow_access=True)
async def oauth_get_code(context, request):
    oauth_utility = getUtility(IOAuth)
    if 'client_id' in request.GET:
        client_id = request.GET['client_id']
    else:
        client_id = oauth_utility.client_id

    scopes = []
    if hasattr(request, '_container_id'):
        scopes.append(request._container_id)
    elif 'scope' in request.GET:
        scopes.append(request.GET['scope'])

    result = await oauth_utility.auth_code(scopes, client_id)
    return {
        'auth_code': result
    }


@configure.service(context=IContainer, name='@oauthgetcode', method='OPTIONS',
                   permission='guillotina.GetOAuthGrant')
class OptionsGetCredentials(DefaultOPTIONS):

    async def __call__(self):
        headers = {}
        allowed_headers = ['Content-Type'] + app_settings['cors']['allow_headers']
        headers['Access-Control-Allow-Headers'] = ','.join(allowed_headers)
        headers['Access-Control-Allow-Methods'] = ','.join(
            app_settings['cors']['allow_methods'])
        headers['Access-Control-Max-Age'] = str(app_settings['cors']['max_age'])
        headers['Access-Control-Allow-Origin'] = ','.join(
            app_settings['cors']['allow_origin'])
        headers['Access-Control-Allow-Credentials'] = 'True'
        headers['Access-Control-Expose-Headers'] = \
            ', '.join(app_settings['cors']['allow_headers'])

        resp = await oauth_get_code(self.context, self.request)
        return Response(response=resp, headers=headers, status=200)
