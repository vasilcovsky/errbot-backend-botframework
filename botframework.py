import base64
import copyreg
import datetime
import json
import logging
import re
import threading
import time
from collections import namedtuple
from time import sleep

import jsonpickle
import jwt
import requests
from cryptography.x509 import load_der_x509_certificate
from errbot.backends.base import Message
from errbot.core import ErrBot
from errbot.core_plugins import flask_app
from flask import request, abort
from lib.bf_card import build_bf_card
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
    )
    r.raise_for_status()

    r = r.json()
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
    def message_id(self):
        s = self.id.split(';')
        if len(s) == 1:
            return None
        if not s[1].startswith("messageid="):
            return None
        return s[1][len("messageid="):]

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
        self._default_service_url = "https://smba.trafficmanager.net/emea/"
        self._saved_service_url = False
        self._keys_url = "https://login.botframework.com/v1/.well-known/keys"
        self._keys = None
        self._keys_time = None
        self._conversation_members_cache = {}
        self._cache_lock = threading.Lock()

        self._register_identifiers_pickling()

    @staticmethod
    def _unpickle_identifier(identifier_str):
        return BotFramework.__build_identifier(identifier_str)

    @staticmethod
    def _pickle_identifier(identifier):
        return BotFramework._unpickle_identifier, (str(identifier),)

    def _register_identifiers_pickling(self):
        class JsonPickleHandler(jsonpickle.handlers.BaseHandler):
            def __init__(self, bot):
                self.bot = bot
            def flatten(self, obj, data):
                data["str"] = str(obj)
                return data
            def restore(self, obj):
                return self.bot.build_identifier(obj["str"])

        """
        Taken from SlackBackend._register_identifiers_pickling
        """
        BotFramework.__build_identifier = self.build_identifier
        for cls in (BFPerson, BFRoomOccupant, BFRoom):
            copyreg.pickle(cls, BotFramework._pickle_identifier, BotFramework._unpickle_identifier)
            jsonpickle.handlers.register(cls, JsonPickleHandler(self))

    def _load_persistent_stuff(self):
        self._service_url = self.get("service_url", self._default_service_url)

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

    def _build_activity(self, to, frm, message_type, body, conversation, parent_msg):
        payload = {
            'type': message_type,
            'conversation': conversation.raw,
            'service_url': self._service_url,
        }

        if to is not None:
            if isinstance(to, BFPerson) or isinstance(to, BFRoomOccupant):
                payload['recipient'] = to.to_bf_subject()
            elif to is BFRoom:
                pass

        if frm is not None:
            payload['from'] = frm.to_bf_subject()
        if body is not None:
            payload['text'] = body.lstrip()
            payload['textFormat'] = 'markdown'

        if parent_msg is not None:
            payload["replyToId"] = conversation.id

        return Activity(payload)

    def _build_conversation_for_id(self, id, parent_msg):
        if id is None:
            raise ValueError("id is None")
        if isinstance(id, BFRoomOccupant):
            return self._build_conversation_for_id(id.room, parent_msg)
        elif isinstance(id, BFRoom):
            id2 = None
            if parent_msg:
                if "conversation" in parent_msg.extras and parent_msg.extras["conversation"].message_id is not None:
                    id2 = parent_msg.extras["conversation"].id
                elif "message_id" in parent_msg.extras:
                    id2 = "%s;messageid=%s" % (id.room_id, parent_msg.extras["message_id"])
                elif "conversation" in parent_msg.extras:
                    id2 = parent_msg.extras["conversation"].id
            if id2 is None:
                id2 = id.room_id

            return Conversation({
                "conversationType": "channel",
                "id": id2,
                "isGroup": True,
                "tenantId": id.tenant_id,
            })
        elif isinstance(id, BFPerson):
            c = self.get_personal_conversation(id.person)
            if c is None:
                raise ValueError("no conversation for %s found" % str(id))
            return c
        else:
            raise ValueError("Unknown id type %s" % type(id).__name__)

    def _build_message(self, msg):
        return self._build_activity(msg.to, msg.frm, "message", msg.body, self._build_conversation_for_id(msg.to, msg.parent), msg.parent)

    def _build_card(self, card):
        activity = self._build_activity(card.to, card.frm, "message", None, self._build_conversation_for_id(card.to, card.parent), card.parent)
        activity.raw["attachments"] = [build_bf_card(card)]
        return activity

    def _build_feedback(self, msg):
        return self._build_activity(None, self.bot_identifier, 'typing', None, msg.extras["conversation"], msg)

    def _build_conversation_url(self, conversation_id):
        url = "%sv3/conversations" % self._service_url
        if conversation_id is not None:
            url += "/%s" % conversation_id
        return url

    def _build_activity_url(self, activity):
        url = self._build_conversation_url(activity.conversation.id)
        url += "/activities"
        if activity.reply_to_id is not None:
            url += "/{}".format(activity.reply_to_id)
        return url

    def _get(self, url):
        headers = {
        }

        if not self._emulator_mode:
            access_token = self._ensure_token()
            headers['Authorization'] = 'Bearer ' + access_token

        r = requests.get(
            url,
            headers=headers
        )

        r.raise_for_status()
        return r.json()

    def _post(self, url, data):
        headers = {
            'Content-Type': 'application/json'
        }

        if not self._emulator_mode:
            access_token = self._ensure_token()
            headers['Authorization'] = 'Bearer ' + access_token

        r = requests.post(
            url,
            data=data,
            headers=headers
        )

        r.raise_for_status()
        if r.text is None or r.text == "":
            return None
        return r.json()

    def _send_activity(self, activity):
        """Post response to callback url

        Send a reply to URL indicated in serviceUrl from
        Bot Framework's request object.

        @param activity: activity object
        """
        return self._post(self._build_activity_url(activity), json.dumps(activity.raw))

    def _get_conversation_members(self, conversation_id):
        with self._cache_lock:
            if conversation_id in self._conversation_members_cache:
                if time.time() - self._conversation_members_cache[conversation_id]["entryTime"] < 60:
                    return self._conversation_members_cache[conversation_id]["result"]
        r = self._get("%s/members" % self._build_conversation_url(conversation_id))
        with self._cache_lock:
            self._conversation_members_cache[conversation_id] = {
                "entryTime": time.time(),
                "result": r
            }
            for m in r:
                self.store_account(m)
        return r

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
        activity = self._build_message(msg)
        r = self._send_activity(activity)
        msg.extras["message_id"] = r["id"]
        return super(BotFramework, self).send_message(msg)

    def send_card(self, card):
        activity = self._build_card(card)
        r = self._send_activity(activity)
        msg = Message(card.body, card.frm, card.to, card.parent)
        msg.extras["message_id"] = r["id"]
        return msg

    def build_identifier(self, id):
        if id[0] == "#":
            id = id[1:]
            s = id.split("/")
            room_id = s[0]
            conv = self.get_channel_conversation(room_id)
            room = BFRoom.from_bf_conversation(conv, self)
            if len(s) == 1:
                return room
            else:
                person = self.build_identifier(s[1])
                return BFRoomOccupant(person, room)
        else:
            if self.bot_identifier is not None and self.bot_identifier.person == id:
                return self.bot_identifier

            account = self.get_account(id)
            if account is None:
                raise ValueError("unknown id %s" % id)
            return BFPerson.from_bf_account(account)

    def build_reply(self, msg, text=None, private=False, threaded=False):
        return Message(
            body=text,
            parent=msg,
            frm=msg.to,
            to=msg.frm,
            extras=msg.extras,
        )

    def send_feedback(self, msg):
        feedback = self._build_feedback(msg)
        self._send_activity(feedback)

    def change_presence(self, status, message):
        pass

    def query_room(self, room):
        return None

    def rooms(self):
        return []

    @property
    def mode(self):
        return 'BotFramework'

    def set_personal_conversation(self, id, conv):
        self["personal_conversations_%s" % id] = conv.raw

    def get_personal_conversation(self, id):
        c = self.get("personal_conversations_%s" % id, None)
        if c is None:
            return None
        return Conversation(c)

    def set_channel_conversation(self, conv):
        raw = {
            **conv.raw,
            "id": conv.room_id,
        }
        self["channel_conversations_%s" % conv.room_id] = raw

    def get_channel_conversation(self, room_id):
        c = self.get("channel_conversations_%s" % room_id, None)
        if c is None:
            return None
        return Conversation(c)

    def get_all_channel_conversations(self):
        r = []
        for k in self.keys():
            if k.startswith("channel_conversations_"):
                r.append(Conversation(self.get(k)))
        return r

    def store_account(self, account):
        if "userPrincipalName" in account:
            key = "account$%s" % account["userPrincipalName"]
        else:
            key = "account$%s" % account["id"]
        self[key] = account

    def get_account(self, upn):
        key = "account$%s" % upn
        try:
            return self[key]
        except:
            return None

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

            if "serviceUrl" in req and not self._saved_service_url:
                # we assume that this url won't magically change...
                self["service_url"] = req["serviceUrl"]
                self._saved_service_url = True

            activity = Activity(req)
            conv = activity.conversation

            conv_members = self._get_conversation_members(conv.id)
            frm = None
            to = None
            for m in conv_members:
                if m["id"] == req["from"]["id"]:
                    frm = BFPerson.from_bf_account(m)
                if m["id"] == req["recipient"]["id"]:
                    to = BFPerson.from_bf_account(m)

            if to is None:
                # this must be us!
                to = BFPerson.from_bf_account(req['recipient'])
                if errbot.bot_identifier is None:
                    errbot._set_bot_account(req['recipient'])

            # We need to store conversations for channels and personal conversatons as there is no way to figure
            # out in which conversations the bot participates. We need this information in case the bot wants to
            # directly send something into a conversation where only the channel or personal id is known
            if conv.conversation_type == "channel":
                self.set_channel_conversation(conv)
            elif conv.conversation_type == "personal":
                self.set_personal_conversation(frm.person, conv)

            if req['type'] == "conversationUpdate":
                if "membersAdded" in req or "membersRemoved" in req:
                    with self._cache_lock:
                        if conv.room_id is self._conversation_members_cache:
                            del self._conversation_members_cache[conv.room_id]
            if req['type'] == 'message':
                msg = Message(self.strip_mention(req['text']), frm=frm, to=to)
                msg.extras['conversation'] = conv

                if msg.frm is None or msg.to is None:
                    abort(400, "Could not find from/to members")

                if conv.conversation_type == "channel":
                    room = BFRoom.from_bf_conversation(conv, self)
                    msg.frm = BFRoomOccupant(msg.frm, room)
                    msg.to = BFRoomOccupant(msg.to, room)
                elif conv.conversation_type == "personal":
                   pass
                else:
                    log.warning("Unknown conversation type %s" % conv.conversation_type)
                    log.warning("req=%s" % request.data)
                    return

                if msg.body.startswith(errbot.bot_config.BOT_PREFIX):
                    errbot.send_feedback(msg)
                errbot.callback_message(msg)
            return ''

    def strip_mention(self, text):
        return re.sub(r'^<at>([^<]*)<\/at>', '', text.lstrip()).lstrip()
