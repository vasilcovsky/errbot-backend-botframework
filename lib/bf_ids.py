from typing import List

from errbot.backends.base import Person, Room, RoomOccupant


class BFPerson(Person):
    def __init__(self, id, name, given_name, surname, email, upn, aad_object_id):
        self._id = id
        self._name = name
        self._given_name = given_name
        self._surname = surname
        self._email = email
        self._upn = upn
        self._aad_object_id = aad_object_id

    @staticmethod
    def from_bf_account(account):
        return BFPerson(account["id"],
                        account["name"],
                        account.get("givenName", None),
                        account.get("surname", None),
                        account.get("email", None),
                        account.get("userPrincipalName", None),
                        account.get("aadObjectId", None)
                        )

    def to_bf_subject(self):
        r = {
            "id": self.person,
            "name": self._name,
        }
        if self.aad_object_id is not None:
            r["aadObjectId"] = self.aad_object_id
        return r

    def __str__(self):
        return self.aclattr

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
        if self._upn:
            return self._upn
        else:
            return self._id

    @property
    def person(self):
        return self.aclattr

    @property
    def nick(self):
        if self._upn:
            return self._upn
        else:
            return self._name

    @property
    def fullname(self):
        return self._name

    @property
    def email(self):
        return self._email

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
        super().__init__(person._id, person._name, person._given_name, person._surname, person._email, person._upn, person._aad_object_id)
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
