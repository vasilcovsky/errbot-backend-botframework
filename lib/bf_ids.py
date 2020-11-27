from typing import List

from errbot.backends.base import Person, Room, RoomOccupant


class BFPerson(Person):
    def __init__(self, id, name, aad_object_id):
        self._id = id
        self._name = name
        self._aad_object_id = aad_object_id

    @staticmethod
    def from_bf_account(account):
        return BFPerson(account["id"], account["name"], account.get("aadObjectId", None))

    def to_bf_subject(self):
        r = {
            "id": self.person,
            "name": self._name,
        }
        if self.aad_object_id is not None:
            r["aadObjectId"] = self.aad_object_id
        return r

    def __str__(self):
        return "@%s" % self._id

    def __hash__(self):
        return hash(str(self))

    def __eq__(self, other):
        if type(self) != type(other):
            return False
        return str(self) == str(other)

    @property
    def aad_object_id(self):
        return self._aad_object_id

    @property
    def aclattr(self):
        return "@%s" % self._id

    @property
    def person(self):
        return self._id

    @property
    def nick(self):
        return self._name

    @property
    def fullname(self):
        return self._name

    @property
    def client(self):
        return '<not set>'


class BFRoom(Room):
    def __init__(self, room_id, tenant_id, bot):
        self._room_id = room_id
        self._tenant_id = tenant_id
        self._bot = bot

    @staticmethod
    def from_bf_conversation(conversation, bot):
        if conversation is None:
            raise ValueError("conversation is None")
        return BFRoom(conversation.room_id, conversation.tenant_id, bot)

    @property
    def room_id(self):
        return self._room_id

    @property
    def tenant_id(self):
        return self._tenant_id

    @property
    def occupants(self) -> List[RoomOccupant]:
        c = self._bot._get_conversation_members(self.room_id)
        r = []
        for m in c:
            p = BFPerson.from_bf_account(m)
            o = BFRoomOccupant(p, self)
            r.append(o)
        return r

    def __str__(self):
        return "#%s" % self._room_id

    def __hash__(self):
        return hash(str(self))

    def __eq__(self, other):
        if not isinstance(other, BFRoom):
            return False
        return str(self) == str(other)


class BFRoomOccupant(RoomOccupant, BFPerson):
    def __init__(self, person, room):
        super().__init__(person.person, person.nick, person.aad_object_id)
        self._room = room

    @property
    def room(self):
        return self._room

    def __str__(self):
        return "%s/%s" % (str(self.room), super().__str__())

    def __eq__(self, other):
        if not isinstance(other, BFRoomOccupant):
            return False
        return str(self) == str(other)
