#!/usr/bin/env python

import ConfigParser

from oslo_config import cfg


class AttrDict(dict):
    def __getattr__(self, attr):
        try:
            return self[attr]
        except KeyError:
            raise AttributeError(attr)


class Config(AttrDict):
    def read(self, filename):
        conf = ConfigParser.ConfigParser()
        conf.read(filename)
        self['DEFAULT'] = AttrDict(conf.defaults())
        for section in conf.sections():
            self[section] = AttrDict(conf.items(section))


CONF = Config()
OSLO_CONF = cfg.CONF
