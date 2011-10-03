#!/usr/bin/env python
#
# Copyright 2011 Oli McCormack. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Models for Prometheus based Application."""

__author__ = "dev@olimcc.com (Oliver McCormack)"

import os
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.api import memcache


class DataStoreEmptyError(Exception):
  """Thrown if no data exists in datastore"""
  

class User(db.Model):
  """Model of User entity."""
  user = db.UserProperty(auto_current_user=True)
  created_by = db.UserProperty(auto_current_user_add=True)
  created_at = db.DateTimeProperty(auto_now_add=True)
  updated_by = db.UserProperty(auto_current_user=True)
  updated_at = db.DateTimeProperty(auto_now=True)

  @classmethod
  def current(cls):
    user_list = cls.all().filter('user =', users.get_current_user()).fetch(1)
    if user_list:
      return user_list[0]
    else:
      new_user = cls()
      new_user.put()
      return new_user

      
class Site(db.Model):
  """Model for stored site."""
  path = db.StringProperty()
  owner = db.ReferenceProperty(User, collection_name='site_set')
  created_by = db.UserProperty(auto_current_user_add=True)
  created_at = db.DateTimeProperty(auto_now_add=True)
  updated_by = db.UserProperty(auto_current_user=True)
  updated_at = db.DateTimeProperty(auto_now=True)