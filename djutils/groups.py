import datajoint as dj
from datajoint.hash import key_hash
from datajoint.utils import user_choice
from .context import foreigns
from .errors import MissingError
from .logging import logger


def master_definition(name, comment, length):
    return """
    {name}_id                       : char({length})    # {comment}
    ---
    members                         : int unsigned      # number of members
    {name}_ts = CURRENT_TIMESTAMP   : timestamp         # automatic timestamp
    """.format(
        name=name,
        length=length,
        comment=comment,
    )


def member_definition(foriegn_keys):
    return """
    -> master
    {foriegn_keys}
    ---
    member_id                       : int unsigned      # member id
    """.format(
        foriegn_keys="\n    ".join([f"-> {f}" for f in foriegn_keys]),
    )


note_definition = """
    -> master
    note                            : varchar(1024)     # group note
    ---
    note_ts = CURRENT_TIMESTAMP     : timestamp         # automatic timestamp
    """


class Master:
    @property
    def key_source(self):
        if self._key_source is None:

            self._key_source = self.keys[0].proj()

            for key in self.keys[1:]:
                self._key_source *= key.proj()

        return self._key_source

    @classmethod
    def fill(cls, restriction, note=None, *, prompt=True, silent=False):
        """Creates a hash for the restricted tuples, and inserts into master, member, and note tables

        Parameters
        ----------
        restriction : datajoint restriction
            used to restrict key_source
        note : str | None
            note to attach to the tuple set
        """
        keys = cls.key_source.restrict(restriction)
        size = len(keys)

        hashes = keys.fetch(as_dict=True, order_by=keys.primary_key)
        hashes = dict([[i, key_hash(k)] for i, k in enumerate(hashes)])

        key = {f"{cls.name}_id": key_hash(hashes)}

        if cls & key:
            assert (cls & key).fetch1("members") == len(cls.Member & key)

            if not silent:
                logger.info(f"{key} already exists.")

        elif not prompt or user_choice(f"Insert group with {size} keys?") == "yes":
            cls.insert1(dict(key, members=size))

            members = keys.fetch(as_dict=True, order_by=cls.key_source.primary_key)
            members = [dict(member_id=i, **key, **k) for i, k in enumerate(members)]
            cls.Member.insert(members)

            if not silent:
                logger.info(f"{key} inserted.")

        else:
            if not silent:
                logger.info(f"{key} not inserted.")

            return

        if note:
            if not silent:
                logger.info(f"Note for {key} inserted.")

            cls.Note.insert1(dict(key, note=note), skip_duplicates=True)

        return key

    @classmethod
    def get(cls, restriction):
        """
        Parameters
        ----------
        restriction : datajoint restriction
            used to restrict key_source

        Returns
        -------
        dj.Lookup
            single tuple that matches restriction
        """
        key = cls.key_source & restriction
        key = cls.aggr(cls.Member * key, n="count(*)") & f"n = {len(key)}"

        if key:
            return cls & key.fetch1(dj.key)
        else:
            raise MissingError("Member set does not exist.")

    @property
    def members(self):
        key, n = self.fetch1(dj.key, "members")
        members = self.Member & key

        if len(members) == n:
            return members
        else:
            raise MissingError("Members are missing.")


def group(schema):
    def decorate(cls):
        cls = setup(cls, schema)
        return cls

    return decorate


def setup(cls, schema):

    name = str(cls.name)
    comment = str(cls.comment)
    keys = tuple(cls.keys)
    length = int(getattr(cls, "length", 32))
    length = max(0, min(length, 32))

    foriegn_keys, context = foreigns(keys, schema)

    member_attr = dict(
        definition=member_definition(foriegn_keys),
    )
    Member = type("Member", (dj.Part,), member_attr)

    note_attr = dict(
        definition=note_definition,
    )
    Note = type("Note", (dj.Part,), note_attr)

    master_attr = dict(
        definition=master_definition(name, comment, length),
        name=name,
        comment=comment,
        keys=keys,
        length=length,
        Member=Member,
        Note=Note,
        _key_source=None,
    )
    cls = type(cls.__name__, (Master, cls, dj.Lookup), master_attr)
    cls = schema(cls, context=context)
    return cls
