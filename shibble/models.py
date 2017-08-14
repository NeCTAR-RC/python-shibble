import logging

from sqlalchemy import Column, Integer, String, PickleType, DateTime, Enum
from sqlalchemy.ext.declarative import declarative_base

from shibble import cfg

Base = declarative_base()
CONF = cfg.CONF
LOG = logging.getLogger('shibble.models')


class User(Base):
    __tablename__ = 'user'
    id = Column(Integer, primary_key=True)
    user_id = Column(String(64), unique=True)
    displayname = Column(String(250))
    email = Column(String(250))
    password = Column(String(32))
    state = Column(Enum("new", "registered", "created"))
    terms = Column(DateTime())
    shibboleth_attributes = Column(PickleType)

    def __init__(self, user_id):
        self.user_id = user_id
        self.state = "new"

    def __repr__(self):
        return "<Shibboleth User '%d', '%s')>" % (self.id, self.displayname)


def create_shibboleth_user(db, shib_attrs):
    """Create a new user from the Shibboleth attributes

    Required Shibboleth attributes are `id`, `fullname` and `mail`

    Return a newly created user.
    """
    # add shibboleth user
    shibuser = User(shib_attrs["id"])
    db.add(shibuser)
    db.commit()
    return shibuser


def update_shibboleth_user(db, shib_user, shib_attrs):
    """Update a Shibboleth User with new details passed from
    Shibboleth.
    """
    shib_user.displayname = shib_attrs["fullname"]
    shib_user.email = shib_attrs["mail"]
    shib_user.shibboleth_attributes = shib_attrs
    db.commit()


def update_user_state(db, shib_attrs, state):
    shib_user = db.query(User).filter_by(
        user_id=shib_attrs["id"]).first()
    shib_user.state = state
    db.commit()
