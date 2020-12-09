import base64
import json
import logging
import datetime
import requests

from time import sleep
from urllib.parse import urljoin
from collections import namedtuple

import jwt
from flask import request
from cryptography.x509 import load_der_x509_certificate
from errbot.core import ErrBot
from errbot.core_plugins import flask_app
from errbot.backends.base import Message, Person
from lib.bf_ids import BFPerson, BFRoom, BFRoomOccupant

log = logging.getLogger('errbot.backends.botframework')
authtoken = namedtuple('AuthToken', 'access_token, expired_at')


def from_now(seconds):
    now = datetime.datetime.now()
    return now + datetime.timedelta(seconds=seconds)


def auth(appId, appPasswd):
    form = {
        'grant_type': 'client_credentials',
        'scope': 'https://api.botframework.com/.default',
        'client_id': appId,
        'client_secret': appPasswd,
    }

    r = requests.post(
        'https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token',
        data=form
    ).json()

    expires_in = r['expires_in']
    expired_at = from_now(expires_in)
    token = authtoken(r['access_token'], expired_at)

    return token

class Conversation:
    def __init__(self, conversation):
        self._conversation = conversation

    @property
    def raw(self):
        return self._conversation

    @property
    def id(self):
        return self._conversation['id']

    @property
    def room_id(self):
        return self.id.split(';')[0]

    @property
    def aad_object_id(self):
        return self._conversation["aadObjectId"]

    @property
    def tenant_id(self):
        return self._conversation["tenantId"]

    @property
    def conversation_type(self):
        return self._conversation['conversationType']

class Activity:
    """ Wrapper on Activity object.

    See more:
        https://docs.microsoft.com/en-us/bot-framework/rest-api/bot-framework-rest-connector-api-reference#activity-object
    """

    def __init__(self, activity):
        self._activity = activity
        self._conversation = Conversation(self._activity["conversation"])

    @property
    def raw(self):
        return self._activity

    @property
    def conversation(self):
        return self._conversation

    @property
    def id(self):
        if 'id' not in self._activity:
            return None
        return self._activity['id']

    @property
    def reply_to_id(self):
        if 'replyToId' not in self._activity:
            return None
        return self._activity["replyToId"]

    @property
    def service_url(self):
        return self._activity['serviceUrl']


class BotFramework(ErrBot):
    """Errbot Backend for Bot Framework"""

    def __init__(self, config):
        super(BotFramework, self).__init__(config)

        identity = config.BOT_IDENTITY
        self._appId = identity.get('appId', None)
        self._appPassword = identity.get('appPassword', None)
        self._token = None
        self._emulator_mode = self._appId is None or self._appPassword is None
        self._keys_url = "https://login.botframework.com/v1/.well-known/keys"
        self._keys = None
        self._keys_time = None

        self._register_identifiers_pickling()

    @staticmethod
    def _unpickle_identifier(identifier_str):
        return BotFramework.__build_identifier(identifier_str)

    @staticmethod
    def _pickle_identifier(identifier):
        return BotFramework._unpickle_identifier, (str(identifier),)

    def _register_identifiers_pickling(self):
        """
        Taken from SlackBackend._register_identifiers_pickling
        """
        BotFramework.__build_identifier = self.build_identifier
        for cls in (BFPerson, BFRoomOccupant, BFRoom):
            copyreg.pickle(cls, BotFramework._pickle_identifier, BotFramework._unpickle_identifier)

    def _load_persistent_stuff(self):
        self.bot_account = self.get("bot_account", None)
        if self.bot_account is not None:
            self.bot_identifier = BFPerson.from_bf_account(self.bot_account)
        else:
            self.bot_identifier = None

    def _set_bot_account(self, account):
        self["bot_account"] = account
        self.bot_identifier = BFPerson.from_bf_account(account)

    def _ensure_token(self):
        """Keep OAuth token valid"""
        now = datetime.datetime.now()
        if not self._token or self._token.expired_at <= now:
            self._token = auth(self._appId, self._appPassword)
        return self._token.access_token

    def _ensure_keys(self):
        with self._cache_lock:
            if self._keys is not None and time.time() - self._keys_time < 60 * 60:
                return
            keys = requests.get(self._keys_url).json()
            self._keys = {}
            for k in keys["keys"]:
                if "x5c" in k and "x5t" in k:
                    b = base64.b64decode(k["x5c"][0])
                    x5c = load_der_x509_certificate(b)
                    self._keys[k["x5t"]] = x5c
            self._keys_time = time.time()

    def _get_key(self, x5t):
        self._ensure_keys()
        with self._cache_lock:
            return self._keys.get(x5t, None)

    def _validate_jwt_token(self, auth_header):
        try:
            if not auth_header.startswith("Bearer "):
                return False
            token = auth_header[len("Bearer "):]
            header = jwt.get_unverified_header(token)
            if header["alg"] != "RS256" or header["typ"] != "JWT":
                return False
            k = self._get_key(header["x5t"])
            if k is None:
                return False
            k = k.public_key()
            token = jwt.decode(token,
                               key=k,
                               audience=self.bot_config.BOT_IDENTITY["appId"],
                               issuer="https://api.botframework.com",
                               algorithms=["RS256"])
            return True
        except Exception as e:
            return False

    def _build_reply(self, msg):
        conversation = msg.extras['conversation']
        payload = {
            'type': 'message',
            'conversation': conversation.conversation,
            'from': msg.to.subject,
            'recipient': msg.frm.subject,
            'replyToId': conversation.conversation_id,
            'text': msg.body
        }
        return activity(conversation.reply_url, payload)

    def _build_feedback(self, msg):
        conversation = msg.extras['conversation']
        payload = {
            'type': 'typing',
            'conversation': conversation.conversation,
            'from': msg.to.subject,
            'replyToId': conversation.conversation_id,
        }
        return activity(conversation.reply_url, payload)

    def _send_reply(self, response):
        """Post response to callback url

        Send a reply to URL indicated in serviceUrl from
        Bot Framework's request object.

        @param response: activity object
        """
        headers = {
            'Content-Type': 'application/json'
        }

        if not self._emulator_mode:
            access_token = self._ensure_token()
            headers['Authorization'] = 'Bearer ' + access_token

        r = requests.post(
            response.post_url,
            data=json.dumps(response.payload),
            headers=headers
        )

        r.raise_for_status()

    def serve_forever(self):
        self._ensure_keys()
        self._load_persistent_stuff()
        self._init_handler(self)
        self.connect_callback()

        try:
            while True:
                sleep(1)
        except KeyboardInterrupt:
            log.info("Interrupt received, shutting down")
        finally:
            self.disconnect_callback()
            self.shutdown()

    def send_message(self, msg):
        response = self._build_reply(msg)
        self._send_reply(response)
        super(BotFramework, self).send_message(msg)

    def build_identifier(self, user):
        return Identifier(user)

    def build_reply(self, msg, text=None, private=False, threaded=False):
        return Message(
            body=text,
            parent=msg,
            frm=msg.frm,
            to=msg.to,
            extras=msg.extras,
        )

    def send_feedback(self, msg):
        feedback = self._build_feedback(msg)
        self._send_reply(feedback)

    def build_conversation(self, conv):
        return Conversation(conv)

    def change_presence(self, status, message):
        pass

    def query_room(self, room):
        return None

    def rooms(self):
        return []

    @property
    def mode(self):
        return 'BotFramework'

    def _init_handler(self, errbot):
        @flask_app.route('/botframework', methods=['GET', 'OPTIONS'])
        def get_botframework():
            return ''

        @flask_app.route('/botframework', methods=['POST'])
        def post_botframework():
            if "Authorization" not in request.headers:
                abort(403, "Forbidden")
            auth_header = request.headers["Authorization"]
            if not self._validate_jwt_token(auth_header):
                abort(403, "Forbidden")

            req = request.json
            log.debug('received request: type=[%s] channel=[%s]',
                      req['type'], req['channelId'])
            if req['type'] == 'message':
                msg = Message(self.strip_mention(req['text']))
                msg.frm = errbot.build_identifier(req['from'])
                msg.to = errbot.build_identifier(req['recipient'])
                msg.extras['conversation'] = errbot.build_conversation(req)

                if errbot.bot_identifier is None:
                    errbot._set_bot_account(req['recipient'])

                if msg.body.startswith(errbot.bot_config.BOT_PREFIX):
                    errbot.send_feedback(msg)
                errbot.callback_message(msg)
            return ''

    def strip_mention(self, text):
        return re.sub(r'^<at>([^<]*)<\/at>', '', text.lstrip()).lstrip()
